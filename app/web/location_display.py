"""设备当前位置：纯文本展示（卫星 / 网络）。"""

from __future__ import annotations

from app.db.models import Device
from app.geo.gcj02 import wgs84_to_gcj02


def device_location_text(dev: Device) -> str:
    src = (dev.last_display_source or "").strip()
    if src == "gps":
        addr = (dev.last_gps_address or "").strip()
        if addr:
            return f"卫星定位：{addr}"
        if dev.last_gps_lat is not None and dev.last_gps_lng is not None:
            lo_g, la_g = wgs84_to_gcj02(float(dev.last_gps_lng), float(dev.last_gps_lat))
            return (
                f"卫星定位：{la_g:.5f}，{lo_g:.5f}（坐标，地址解析中或未配置地图服务 Key）"
            )
        if dev.last_lat is not None and dev.last_lng is not None:
            return f"卫星定位：{dev.last_lat:.5f}，{dev.last_lng:.5f}（坐标，地址解析中或未配置地图服务 Key）"
        return "—"
    if src == "net":
        addr = (dev.last_net_address or "").strip()
        rad = dev.last_net_radius
        extra = f"（约 ±{rad} 米）" if rad and rad > 0 else ""
        if addr:
            return f"网络定位：{addr}{extra}"
        if dev.last_lat is not None and dev.last_lng is not None:
            return f"网络定位：{dev.last_lat:.5f}，{dev.last_lng:.5f}（坐标）{extra}"
        return "—"
    if dev.last_lat is not None and dev.last_lng is not None:
        return f"{dev.last_lat:.5f}，{dev.last_lng:.5f}（坐标）"
    return "—"
