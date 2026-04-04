"""地图开放平台 REST（当前实现域名 amap.com）：网络定位 + 逆地理。"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)

IOT_URL = "https://restapi.amap.com/v5/position/IoT"
REGEO_URL = "https://restapi.amap.com/v3/geocode/regeo"


def _mnc_two(mnc: str) -> str:
    s = (mnc or "").strip()
    if s.isdigit() and len(s) < 2:
        return s.zfill(2)
    return s or "00"


def _bts_signal_dbm(raw: str) -> int:
    """转换为协议要求的 dBm（约 -113..-1，正数按 2*x-113）。"""
    try:
        sig = int(raw)
    except ValueError:
        return -100
    if sig >= 0:
        sig = min(-1, sig * 2 - 113)
    return max(-130, min(-1, sig))


def _network_for_cells(cells: list[dict[str, str]]) -> str:
    """智能硬件定位 2.0：network 取值 GSM/WCDMA/NR 等；大 cellid 常见于 LTE。"""
    if not cells:
        return "GSM"
    try:
        cid = int(str(cells[0].get("cell_id", "0")).strip())
        if cid > 65535:
            return "LTE"
    except ValueError:
        pass
    return "GSM"


def _bts_segment(cells: list[dict[str, str]]) -> tuple[str | None, str | None]:
    """2.0 主基站：mcc,mnc,lac,cellid,signal,cage；周边：lac,cellid,signal,cage（| 分隔）。"""
    if not cells:
        return None, None
    first = cells[0]
    sig = _bts_signal_dbm(str(first.get("signal", "-100")))
    # cage：基站新鲜度（秒），无数据时 0（文档默认）
    seg0 = ",".join(
        [
            first.get("mcc", "460"),
            _mnc_two(first.get("mnc", "0")),
            first.get("lac", "0"),
            first.get("cell_id", "0"),
            str(sig),
            "0",
        ]
    )
    rest: list[str] = []
    for c in cells[1:]:
        rs = _bts_signal_dbm(str(c.get("signal", "-100")))
        rest.append(
            ",".join(
                [
                    c.get("lac", "0"),
                    c.get("cell_id", "0"),
                    str(rs),
                    "0",
                ]
            )
        )
    near = "|".join(rest) if rest else None
    return seg0, near


def _macs_segment(wifi: list[dict[str, str]]) -> str | None:
    if len(wifi) < 2:
        return None
    parts: list[str] = []
    for w in wifi[:30]:
        mac = (w.get("mac") or "").strip().lower().replace("-", ":")
        if not mac or mac.count(":") != 5:
            continue
        try:
            rssi = int(w.get("rssi", "-80"))
        except ValueError:
            rssi = -80
        ssid = (w.get("name") or "").strip() or " "
        if "," in ssid or "|" in ssid:
            ssid = " "
        parts.append(f"{mac},{rssi},{ssid},0")
    if len(parts) < 2:
        return None
    return "|".join(parts)


async def amap_iot_locate(
    key: str,
    cells: list[dict[str, str]],
    wifi: list[dict[str, str]],
    diu: str,
) -> tuple[float, float, int] | None:
    """返回 (lng, lat, radius) GCJ-02，失败返回 None。"""
    if not key.strip():
        return None
    bts, nearbts = _bts_segment(cells)
    macs = _macs_segment(wifi)
    # 仅基站、或仅 WiFi（含单热点 mmac）均可尝试
    if not bts and not wifi:
        return None

    q: dict[str, Any] = {
        "key": key.strip(),
        "cdma": "0",
        "diu": diu[:32],
        "output": "json",
    }
    if bts:
        # 2.0：1=移动网络，2=wifi；移动网络须 cdma、network、bts
        q["accesstype"] = "1"
        q["network"] = _network_for_cells(cells)
        q["bts"] = bts
        if nearbts:
            q["nearbts"] = nearbts
        if macs:
            q["macs"] = macs
    else:
        q["accesstype"] = "2"
        q["network"] = "GSM"
        w0 = wifi[0]
        m = (w0.get("mac") or "").strip().lower().replace("-", ":")
        try:
            r0 = int(w0.get("rssi", "-80"))
        except ValueError:
            r0 = -80
        ss0 = (w0.get("name") or " ").strip() or " "
        if "," in ss0 or "|" in ss0:
            ss0 = " "
        # mmac：mac,signal,ssid,fresh（fresh 秒，默认 0）
        q["mmac"] = f"{m},{r0},{ss0},0"
        if macs:
            q["macs"] = macs

    # 智能硬件定位 2.0 文档：POST；参数 application/x-www-form-urlencoded
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            r = await client.post(IOT_URL, data=q)
            r.raise_for_status()
            data = r.json()
    except Exception:
        logger.exception("地图 IoT 定位请求失败 diu=%s", diu)
        return None

    if str(data.get("status")) != "1":
        logger.warning("地图 IoT 定位业务失败 info=%s", data.get("info"))
        return None
    pos = data.get("position") or {}
    loc = pos.get("location")
    if not loc or "," not in str(loc):
        return None
    try:
        lng_s, lat_s = str(loc).split(",", 1)
        lng, lat = float(lng_s), float(lat_s)
    except ValueError:
        return None
    try:
        radius = int(pos.get("radius", 0))
    except (TypeError, ValueError):
        radius = 0
    return lng, lat, radius


async def amap_regeo(key: str, lng: float, lat: float) -> str | None:
    """输入 GCJ-02 经纬度，返回结构化地址文本。"""
    if not key.strip():
        return None
    q = {
        "key": key.strip(),
        "location": f"{lng:.6f},{lat:.6f}",
        "radius": "1000",
        "extensions": "base",
        "output": "json",
    }
    url = f"{REGEO_URL}?{urlencode(q)}"
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            r = await client.get(url)
            r.raise_for_status()
            data = r.json()
    except Exception:
        logger.exception("地图逆地理请求失败")
        return None
    if str(data.get("status")) != "1":
        logger.warning("地图逆地理业务失败 info=%s", data.get("info"))
        return None
    rege = data.get("regeocode") or {}
    addr = rege.get("formatted_address")
    return str(addr).strip() if addr else None
