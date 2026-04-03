"""从 UD 族 CSV parts 解析基站与 WiFi 指纹（协议附录一）。"""

from __future__ import annotations

from typing import Any


def parse_ud_lbs_wifi(parts: list[str]) -> dict[str, Any]:
    """返回 cells / wifi 列表，供网络定位 API 使用。"""
    cells: list[dict[str, str]] = []
    wifi: list[dict[str, str]] = []
    out: dict[str, Any] = {"cells": cells, "wifi": wifi}
    if len(parts) < 18:
        return out
    try:
        n = int(parts[17])
    except ValueError:
        return out
    if n < 0 or n > 8:
        return out

    i = 18
    if n > 0:
        need = i + 1 + 5 + 3 * (n - 1)
        if len(parts) < need:
            return out
        i += 1  # 连接时延等，跳过
        mcc, mnc = parts[i], parts[i + 1]
        lac, cid, sig = parts[i + 2], parts[i + 3], parts[i + 4]
        i += 5
        cells.append({"mcc": mcc, "mnc": mnc, "lac": lac, "cell_id": cid, "signal": sig})
        for _ in range(n - 1):
            lac, cid, sig = parts[i], parts[i + 1], parts[i + 2]
            i += 3
            cells.append({"mcc": mcc, "mnc": mnc, "lac": lac, "cell_id": cid, "signal": sig})

    if len(parts) <= i:
        return out
    try:
        nw = int(parts[i])
    except ValueError:
        return out
    i += 1
    nw = max(0, min(nw, 12))
    for _ in range(nw):
        if len(parts) < i + 3:
            break
        name, mac, rssi = parts[i], parts[i + 1], parts[i + 2]
        i += 3
        wifi.append({"name": name, "mac": mac, "rssi": rssi})
    return out


def normalize_lbs_signal(sig: str) -> int:
    """协议：若为正值则按 2*x-113 转为 dBm 量级。"""
    try:
        v = int(sig)
    except ValueError:
        return -100
    if v >= 0:
        return min(-1, v * 2 - 113)
    return max(-130, min(-1, v))
