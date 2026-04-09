from __future__ import annotations

import asyncio
import copy
import hashlib
import logging
import socket
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import FILES_DIR, TCP_KEEPALIVE_IDLE_SEC
from app.device_connections import get_connection_registry
from app.db.models import CommandEvent, Device, RawMessage
from app.db.session import SessionLocal
from app.protocol.dispatch import OutboundSeq, build_replies
from app.protocol.framing import FrameBuffer, ParsedFrame, frame_to_bytes
from app.geo.gcj02 import wgs84_to_gcj02
from app.protocol.parsers.registry import hex_preview, parse_command, summary_to_json
from app.services.amap_enrich import schedule_amap_location_enrich
from app.web.amap_key_store import get_amap_key

logger = logging.getLogger(__name__)

_active_connections: set[str] = set()
_lock = asyncio.Lock()

# 持有一次性地图增强任务，避免被 GC 提前回收导致未写回地址
_amap_enrich_tasks: set[asyncio.Task] = set()

_LOCATION_CMDS = frozenset(
    {"UD", "UD2", "AL", "GETLOC", "CLOCKIN", "CLOCKOUT", "WT"}
)


def _spawn_amap_location_enrich(
    device_id: str,
    parsed: dict,
    location_apply_seq: int,
    command_event_id: int,
) -> None:
    t = asyncio.create_task(
        schedule_amap_location_enrich(
            device_id,
            parsed,
            location_apply_seq,
            command_event_id,
        )
    )
    _amap_enrich_tasks.add(t)
    t.add_done_callback(_amap_enrich_tasks.discard)


async def active_connection_count() -> int:
    async with _lock:
        return len(_active_connections)


async def _get_or_create_device(session: AsyncSession, frame: ParsedFrame) -> Device:
    """查询或新建 Device 行并更新 last_seen，返回行对象供后续复用（避免重复 SELECT）。"""
    now = datetime.utcnow()
    r = await session.execute(select(Device).where(Device.device_id == frame.device_id))
    row = r.scalar_one_or_none()
    if row is None:
        row = Device(
            device_id=frame.device_id,
            vendor=frame.vendor,
            first_seen=now,
            last_seen=now,
        )
        session.add(row)
    else:
        row.vendor = frame.vendor
        row.last_seen = now
    return row


def _apply_lk_device(device: Device, parsed: dict) -> None:
    b = parsed.get("battery")
    if isinstance(b, int):
        device.last_lk_battery = b


def _apply_location_device(device: Device, parsed: dict) -> int | None:
    """有效卫星点：写 WGS84 快照与 GCJ-02 展示坐标；无卫星点由地图服务异步写网络定位。
    返回本帧对应的 location_apply_seq（每条定位上报递增），供异步任务防竞态。"""
    device.location_apply_seq = (device.location_apply_seq or 0) + 1
    seq = device.location_apply_seq
    now = datetime.utcnow()
    if (
        parsed.get("gps_valid")
        and parsed.get("lat") is not None
        and parsed.get("lng") is not None
    ):
        la = float(parsed["lat"])
        lo = float(parsed["lng"])
        device.last_gps_lat = la
        device.last_gps_lng = lo
        device.last_gps_at = now
        lo_g, la_g = wgs84_to_gcj02(lo, la)
        device.last_lat = la_g
        device.last_lng = lo_g
        device.last_loc_at = now
        device.last_display_source = "gps"
    return seq


@dataclass(slots=True)
class _FrameResult:
    replies: list[bytes]
    cmd: str
    device_id: str
    parsed: dict | None
    location_apply_seq: int | None
    command_event_id: int | None


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
) -> _FrameResult:
    """解析入站帧、写入 DB（flush 但不 commit），返回待发送的回复帧及后续元数据。

    调用方负责：先发 TCP 回复，再 session.commit()，最后按需触发地图增强。
    这样设备能在 DB 落盘前就拿到应答，避免因 fsync 延迟导致超时断连。
    """
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

    device = await _get_or_create_device(session, frame)
    await session.flush()
    if cmd == "LK":
        _apply_lk_device(device, parsed)
    location_apply_seq: int | None = None
    if cmd in _LOCATION_CMDS:
        location_apply_seq = _apply_location_device(device, parsed)

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

    cmd_event = CommandEvent(
        device_id=frame.device_id,
        vendor=frame.vendor,
        seq=frame.seq,
        command=cmd,
        summary_json=summary_json,
        media_path=media_path,
        payload_hex_preview=preview,
    )
    session.add(cmd_event)

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

    await session.flush()
    command_event_id = cmd_event.id
    if command_event_id is None:
        logger.error(
            "CommandEvent 未获得主键，地图增强将无法写回该条摘要 device_id=%s cmd=%s",
            frame.device_id,
            cmd,
        )

    return _FrameResult(
        replies=replies,
        cmd=cmd,
        device_id=frame.device_id,
        parsed=parsed if cmd in _LOCATION_CMDS else None,
        location_apply_seq=location_apply_seq,
        command_event_id=command_event_id,
    )


def _configure_tcp_socket(writer: asyncio.StreamWriter) -> None:
    """TCP_NODELAY 禁用 Nagle 缓冲，确保小帧（心跳回复等）立即发出；
    keepalive 探测半开连接。"""
    sock = writer.transport.get_extra_info("socket")
    if sock is None:
        return
    try:
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    except OSError as e:
        logger.debug("TCP_NODELAY: %s", e)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    except OSError as e:
        logger.debug("SO_KEEPALIVE: %s", e)
        return
    idle = TCP_KEEPALIVE_IDLE_SEC
    if idle <= 0:
        return
    try:
        if hasattr(socket, "TCP_KEEPIDLE"):
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, idle)
            if hasattr(socket, "TCP_KEEPINTVL"):
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, max(10, min(30, idle // 4)))
            if hasattr(socket, "TCP_KEEPCNT"):
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)
        elif sys.platform == "darwin" and hasattr(socket, "TCP_KEEPALIVE"):
            # macOS tcp(4)：空闲多久开始发探测，单位为毫秒
            try:
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPALIVE, idle * 1000)
            except OSError as e:
                logger.debug("TCP_KEEPALIVE (darwin): %s", e)
    except OSError as e:
        logger.debug("TCP keepalive 参数: %s", e)


async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    conn_id = str(uuid.uuid4())
    addr = writer.get_extra_info("peername")
    logger.info("新 TCP 连接 conn_id=%s addr=%s", conn_id, addr)
    _configure_tcp_socket(writer)
    async with _lock:
        _active_connections.add(conn_id)

    buf = FrameBuffer()
    outbound_seq = OutboundSeq()
    conn_lock = asyncio.Lock()
    reg = get_connection_registry()
    frame_count = 0
    try:
        while True:
            t_read_start = time.monotonic()
            data = await reader.read(4096)
            t_read_done = time.monotonic()
            if not data:
                logger.info(
                    "conn_id=%s 对端关闭连接（read=0）已处理 %d 帧，本次 read 等待 %.1fms",
                    conn_id, frame_count, (t_read_done - t_read_start) * 1000,
                )
                break
            buf.feed(data)
            frames = list(buf.extract_frames())
            if not frames:
                continue

            results: list[_FrameResult] = []
            async with SessionLocal() as session:
                for frame in frames:
                    frame_count += 1
                    t_frame = time.monotonic()
                    logger.info(
                        "收到帧 #%d conn_id=%s device_id=%s cmd=%s read等待=%.1fms",
                        frame_count, conn_id, frame.device_id, frame.command,
                        (t_read_done - t_read_start) * 1000,
                    )
                    try:
                        async with conn_lock:
                            await reg.bind(
                                frame.device_id,
                                frame.vendor,
                                writer,
                                outbound_seq,
                                conn_id,
                                conn_lock,
                            )
                            async with session.begin_nested():
                                result = await process_inbound_frame(
                                    session, conn_id, frame, outbound_seq,
                                )
                            for rep in result.replies:
                                writer.write(rep)
                            await writer.drain()
                        t_reply = time.monotonic()
                        logger.info(
                            "回复已发送 #%d conn_id=%s cmd=%s 处理+发送=%.1fms",
                            frame_count, conn_id, frame.command,
                            (t_reply - t_frame) * 1000,
                        )
                        results.append(result)
                    except Exception as exc:
                        logger.exception(
                            "帧处理异常 conn_id=%s device_id=%s cmd=%s",
                            conn_id,
                            frame.device_id,
                            frame.command,
                        )
                        try:
                            async with SessionLocal() as err_session:
                                err_session.add(
                                    RawMessage(
                                        connection_id=conn_id,
                                        direction="in",
                                        vendor=frame.vendor,
                                        device_id=frame.device_id,
                                        raw_frame=frame_to_bytes(frame).decode("latin-1"),
                                        parse_ok=False,
                                        error=str(exc),
                                    )
                                )
                                await err_session.commit()
                        except Exception:
                            logger.exception(
                                "帧异常记库失败 conn_id=%s device_id=%s，连接保持",
                                conn_id,
                                frame.device_id,
                            )
                        continue

                t_commit_start = time.monotonic()
                try:
                    await session.commit()
                except Exception:
                    await session.rollback()
                    logger.exception(
                        "批量帧数据落库失败（回复已发出）conn_id=%s 帧数=%d",
                        conn_id, len(results),
                    )
                    results.clear()
                t_commit_done = time.monotonic()
                if results:
                    logger.info(
                        "commit 完成 conn_id=%s 帧数=%d commit耗时=%.1fms",
                        conn_id, len(results),
                        (t_commit_done - t_commit_start) * 1000,
                    )

            for result in results:
                try:
                    if (
                        result.cmd in _LOCATION_CMDS
                        and get_amap_key().strip()
                        and result.location_apply_seq is not None
                        and result.command_event_id is not None
                    ):
                        _spawn_amap_location_enrich(
                            result.device_id,
                            copy.deepcopy(result.parsed),
                            result.location_apply_seq,
                            result.command_event_id,
                        )
                except Exception:
                    logger.exception(
                        "地图增强调度异常（连接保持）conn_id=%s device_id=%s cmd=%s",
                        conn_id, result.device_id, result.cmd,
                    )
    except Exception:
        logger.exception(
            "连接主循环未预期异常 conn_id=%s 已处理 %d 帧", conn_id, frame_count,
        )
    finally:
        logger.info("连接断开 conn_id=%s，执行 unbind", conn_id)
        await reg.unbind_connection(conn_id)
        writer.close()
        try:
            await writer.wait_closed()
        except BaseException:
            pass
        async with _lock:
            _active_connections.discard(conn_id)


async def run_tcp_server(host: str, port: int) -> asyncio.AbstractServer:
    return await asyncio.start_server(handle_client, host, port)
