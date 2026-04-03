from __future__ import annotations

import asyncio
import copy
import hashlib
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import FILES_DIR
from app.device_connections import get_connection_registry
from app.db.models import CommandEvent, Device, RawMessage
from app.db.session import SessionLocal
from app.protocol.dispatch import OutboundSeq, build_replies
from app.protocol.framing import FrameBuffer, ParsedFrame, frame_to_bytes
from app.geo.gcj02 import wgs84_to_gcj02
from app.protocol.parsers.registry import hex_preview, parse_command, summary_to_json
from app.services.amap_enrich import schedule_amap_location_enrich
from app.web.amap_key_store import get_amap_key

_active_connections: set[str] = set()
_lock = asyncio.Lock()


async def active_connection_count() -> int:
    async with _lock:
        return len(_active_connections)


async def _touch_device(session: AsyncSession, frame: ParsedFrame) -> None:
    now = datetime.utcnow()
    r = await session.execute(select(Device).where(Device.device_id == frame.device_id))
    row = r.scalar_one_or_none()
    if row is None:
        session.add(
            Device(
                device_id=frame.device_id,
                vendor=frame.vendor,
                first_seen=now,
                last_seen=now,
            )
        )
    else:
        row.vendor = frame.vendor
        row.last_seen = now


async def _apply_lk_device(session: AsyncSession, frame: ParsedFrame, parsed: dict) -> None:
    r = await session.execute(select(Device).where(Device.device_id == frame.device_id))
    row = r.scalar_one_or_none()
    if row is None:
        return
    b = parsed.get("battery")
    if isinstance(b, int):
        row.last_lk_battery = b


async def _apply_location_device(session: AsyncSession, frame: ParsedFrame, parsed: dict) -> int | None:
    """有效卫星点：写 WGS84 快照与 GCJ-02 展示坐标；无卫星点由地图服务异步写网络定位。
    返回本帧对应的 location_apply_seq（每条定位上报递增），供异步任务防竞态。"""
    r = await session.execute(select(Device).where(Device.device_id == frame.device_id))
    row = r.scalar_one_or_none()
    if row is None:
        return None
    row.location_apply_seq = (row.location_apply_seq or 0) + 1
    seq = row.location_apply_seq
    now = datetime.utcnow()
    if (
        parsed.get("gps_valid")
        and parsed.get("lat") is not None
        and parsed.get("lng") is not None
    ):
        la = float(parsed["lat"])
        lo = float(parsed["lng"])
        row.last_gps_lat = la
        row.last_gps_lng = lo
        row.last_gps_at = now
        lo_g, la_g = wgs84_to_gcj02(lo, la)
        row.last_lat = la_g
        row.last_lng = lo_g
        row.last_loc_at = now
        row.last_display_source = "gps"
    return seq


def _save_media(cmd: str, device_id: str, blob: bytes) -> str | None:
    if not blob:
        return None
    h = hashlib.sha256(blob).hexdigest()[:24]
    ext = ".jpg" if cmd == "SENDPHOTO" else ".bin"
    name = f"{device_id}_{h}{ext}"
    path = FILES_DIR / name
    path.write_bytes(blob)
    return str(path)


async def process_inbound_frame(
    session: AsyncSession,
    connection_id: str,
    frame: ParsedFrame,
    outbound_seq: OutboundSeq,
) -> list[bytes]:
    raw_wire = frame_to_bytes(frame)
    raw_text = raw_wire.decode("latin-1")

    cmd = frame.command
    parsed, media = parse_command(cmd, frame.payload)
    log_parsed = {k: v for k, v in parsed.items() if k != "lbs_wifi"}
    summary_json = summary_to_json(log_parsed)

    media_path = None
    if cmd in ("SENDPHOTO", "JXTK"):
        preview = hex_preview(media or b"")
    elif len(frame.payload) > 256:
        preview = hex_preview(frame.payload)
    else:
        preview = None
    if media and cmd in ("SENDPHOTO", "JXTK"):
        media_path = _save_media(cmd, frame.device_id, media)

    await _touch_device(session, frame)
    await session.flush()
    if cmd == "LK":
        await _apply_lk_device(session, frame, parsed)
    location_apply_seq: int | None = None
    if cmd in ("UD", "AL", "GETLOC", "CLOCKIN", "CLOCKOUT", "WT"):
        location_apply_seq = await _apply_location_device(session, frame, parsed)

    session.add(
        RawMessage(
            connection_id=connection_id,
            direction="in",
            vendor=frame.vendor,
            device_id=frame.device_id,
            raw_frame=raw_text,
            parse_ok=True,
            error=None,
        )
    )

    session.add(
        CommandEvent(
            device_id=frame.device_id,
            vendor=frame.vendor,
            seq=frame.seq,
            command=cmd,
            summary_json=summary_json,
            media_path=media_path,
            payload_hex_preview=preview,
        )
    )

    replies = build_replies(frame, parsed, outbound_seq)

    for rep in replies:
        session.add(
            RawMessage(
                connection_id=connection_id,
                direction="out",
                vendor=frame.vendor,
                device_id=frame.device_id,
                raw_frame=rep.decode("latin-1"),
                parse_ok=True,
                error=None,
            )
        )

    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise

    if (
        cmd in ("UD", "AL", "GETLOC", "CLOCKIN", "CLOCKOUT", "WT")
        and get_amap_key().strip()
        and location_apply_seq is not None
    ):
        asyncio.create_task(
            schedule_amap_location_enrich(
                frame.device_id, copy.deepcopy(parsed), location_apply_seq
            )
        )

    return replies


async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    conn_id = str(uuid.uuid4())
    addr = writer.get_extra_info("peername")
    async with _lock:
        _active_connections.add(conn_id)

    buf = FrameBuffer()
    outbound_seq = OutboundSeq()
    conn_lock = asyncio.Lock()
    reg = get_connection_registry()
    try:
        while True:
            data = await reader.read(4096)
            if not data:
                break
            buf.feed(data)
            for frame in buf.extract_frames():
                async with SessionLocal() as session:
                    try:
                        async with conn_lock:
                            replies = await process_inbound_frame(session, conn_id, frame, outbound_seq)
                            await reg.bind(
                                frame.device_id,
                                frame.vendor,
                                writer,
                                outbound_seq,
                                conn_id,
                                conn_lock,
                            )
                            for rep in replies:
                                writer.write(rep)
                            await writer.drain()
                    except Exception as e:
                        async with SessionLocal() as session2:
                            session2.add(
                                RawMessage(
                                    connection_id=conn_id,
                                    direction="in",
                                    vendor=frame.vendor,
                                    device_id=frame.device_id,
                                    raw_frame=frame_to_bytes(frame).decode("latin-1"),
                                    parse_ok=False,
                                    error=str(e),
                                )
                            )
                            await session2.commit()
                        continue
    finally:
        await reg.unbind_connection(conn_id)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        async with _lock:
            _active_connections.discard(conn_id)


async def run_tcp_server(host: str, port: int) -> asyncio.AbstractServer:
    return await asyncio.start_server(handle_client, host, port)
