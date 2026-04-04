"""收到定位类上报后异步调用地图 REST：卫星点逆地理、无卫星时网络定位 + 逆地理。"""

from __future__ import annotations

import copy
import json
import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.amap.client import amap_iot_locate, amap_regeo
from app.web.amap_key_store import get_amap_key
from app.db.models import CommandEvent, Device
from app.db.session import SessionLocal
from app.geo.gcj02 import wgs84_to_gcj02

logger = logging.getLogger(__name__)


async def schedule_amap_location_enrich(
    device_id: str,
    parsed: dict,
    apply_seq: int,
    command_event_id: int | None = None,
) -> None:
    if not get_amap_key().strip():
        return
    snap = copy.deepcopy(parsed)
    try:
        await _enrich_device_with_amap(
            device_id, snap, apply_seq, command_event_id
        )
    except Exception:
        logger.exception("地图服务位置增强未处理异常 device_id=%s", device_id)


def _seq_matches(dev: Device | None, apply_seq: int) -> bool:
    if dev is None:
        return False
    return (dev.location_apply_seq or 0) == apply_seq


async def _merge_event_reverse_address(event_id: int, addr: str) -> None:
    text = (addr or "").strip()
    if not text:
        return
    async with SessionLocal() as session:
        ev = await session.get(CommandEvent, event_id)
        if ev is None:
            return
        try:
            d = json.loads(ev.summary_json) if ev.summary_json else {}
        except json.JSONDecodeError:
            d = {}
        if not isinstance(d, dict):
            d = {}
        d["reverse_address"] = text
        ev.summary_json = json.dumps(d, ensure_ascii=False)
        await session.commit()
        logger.info(
            "历史记录已写入逆地理地址 command_event_id=%s len=%s",
            event_id,
            len(text),
        )


async def _enrich_device_with_amap(
    device_id: str,
    parsed: dict,
    apply_seq: int,
    command_event_id: int | None,
) -> None:
    key = get_amap_key().strip()
    gps_ok = bool(
        parsed.get("gps_valid")
        and parsed.get("lat") is not None
        and parsed.get("lng") is not None
    )
    fp = parsed.get("lbs_wifi") or {}
    cells = fp.get("cells") or []
    wifi = fp.get("wifi") or []

    if gps_ok:
        la = float(parsed["lat"])
        lo = float(parsed["lng"])
        lo_g, la_g = wgs84_to_gcj02(lo, la)
        addr = await amap_regeo(key, lo_g, la_g)
        if addr and command_event_id is not None:
            await _merge_event_reverse_address(command_event_id, addr)
        if not addr:
            return
        async with SessionLocal() as session:
            dev = await _load_device(session, device_id)
            if not _seq_matches(dev, apply_seq):
                return
            dev.last_gps_address = addr
            await session.commit()
        return

    if not (cells or wifi):
        logger.info(
            "地图增强跳过：无卫星点且解析不到基站/WiFi 指纹（UD 段字段不足或数量为 0）device_id=%s",
            device_id,
        )
        return

    loc = await amap_iot_locate(key, cells, wifi, device_id)
    if not loc:
        return
    lng, lat, rad, iot_text = loc
    addr = await amap_regeo(key, lng, lat)
    if not addr and iot_text:
        addr = iot_text
    if addr and command_event_id is not None:
        await _merge_event_reverse_address(command_event_id, addr)

    async with SessionLocal() as session:
        dev = await _load_device(session, device_id)
        if not _seq_matches(dev, apply_seq):
            return
        if (dev.last_display_source or "").strip() == "gps":
            return
        now = datetime.utcnow()
        dev.last_net_lat = lat
        dev.last_net_lng = lng
        dev.last_net_at = now
        dev.last_net_radius = rad
        if addr:
            dev.last_net_address = addr
        dev.last_lat = lat
        dev.last_lng = lng
        dev.last_loc_at = now
        dev.last_display_source = "net"
        await session.commit()


async def _load_device(session: AsyncSession, device_id: str) -> Device | None:
    r = await session.execute(select(Device).where(Device.device_id == device_id))
    return r.scalar_one_or_none()
