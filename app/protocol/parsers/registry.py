from __future__ import annotations

import json
import re
from typing import Any

from app.protocol.escape import unescape_jxtk
from app.protocol.ud_fingerprint import parse_ud_lbs_wifi


def _text(payload: bytes) -> str:
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError:
        return payload.decode("latin-1")


def _csv(text: str) -> list[str]:
    if not text:
        return []
    return text.split(",")


def _generic(payload: bytes) -> dict[str, Any]:
    t = _text(payload)
    parts = _csv(t)
    cmd = parts[0].strip().upper() if parts else ""
    return {"command": cmd, "parts": parts, "text": t}


def _parse_init(payload: bytes) -> dict[str, Any]:
    p = _csv(_text(payload))
    d: dict[str, Any] = {"command": "INIT", "parts": p}
    if len(p) > 1:
        d["iccid_or_phone"] = p[1]
    if len(p) > 2:
        d["carrier_type"] = p[2]
    if len(p) > 3:
        d["firmware"] = p[3]
    return d


def _parse_lk(payload: bytes) -> dict[str, Any]:
    p = _csv(_text(payload))
    d: dict[str, Any] = {"command": "LK", "parts": p}
    if len(p) > 1:
        try:
            d["steps"] = int(p[1])
        except ValueError:
            d["steps"] = p[1]
    if len(p) > 2:
        d["rolls"] = p[2]
    if len(p) > 3:
        try:
            d["battery"] = int(p[3])
        except ValueError:
            d["battery"] = p[3]
    return d


def _parse_ud_family(payload: bytes, name: str) -> dict[str, Any]:
    t = _text(payload)
    parts = _csv(t)
    d: dict[str, Any] = {"command": name, "parts": parts}
    d["gps_valid"] = False
    if len(parts) > 4 and parts[3].upper() == "A":
        try:
            la = float(parts[4])
            lo = float(parts[6]) if len(parts) > 6 else None
            d["lat"] = la
            d["lng"] = lo
            d["lat_dir"] = parts[5] if len(parts) > 5 else None
            d["lng_dir"] = parts[7] if len(parts) > 7 else None
            if lo is not None and abs(la) >= 1e-5 and abs(float(lo)) >= 1e-5:
                d["gps_valid"] = True
        except (ValueError, IndexError):
            pass
    if len(parts) > 1:
        d["date"] = parts[1]
    if len(parts) > 2:
        d["time"] = parts[2]
    if len(parts) > 14:
        d["terminal_status_hex"] = parts[14]
    d["lbs_wifi"] = parse_ud_lbs_wifi(parts)
    return d


def _parse_lgzone(_payload: bytes) -> dict[str, Any]:
    return {"command": "LGZONE"}


def _parse_getloc(payload: bytes) -> dict[str, Any]:
    return _parse_ud_family(payload, "GETLOC")


def _parse_wt_request(payload: bytes) -> dict[str, Any]:
    return _parse_ud_family(payload, "WT")


def _parse_jxtk(payload: bytes) -> dict[str, Any]:
    parts = payload.split(b",", 5)
    if len(parts) < 6:
        return {"command": "JXTK", "error": "short_payload", "parts_count": len(parts)}
    voice_type = parts[1].decode("ascii", errors="replace")
    fname = parts[2].decode("utf-8", errors="replace")
    cur = parts[3].decode("ascii", errors="replace")
    total = parts[4].decode("ascii", errors="replace")
    raw_audio = parts[5]
    audio = unescape_jxtk(raw_audio)
    return {
        "command": "JXTK",
        "voice_type": voice_type,
        "file": fname,
        "packet": cur,
        "total_packets": total,
        "audio_size": len(audio),
    }


def _parse_sendphoto(payload: bytes) -> dict[str, Any]:
    parts = payload.split(b",", 2)
    if len(parts) < 3:
        return {"command": "SENDPHOTO", "error": "short_payload"}
    try:
        size = int(parts[1].decode("ascii"))
    except ValueError:
        size = -1
    blob = parts[2]
    return {
        "command": "SENDPHOTO",
        "declared_size": size,
        "actual_size": len(blob),
    }


_hex_re = re.compile(r"^[0-9a-fA-F]*$")


def _parse_sendphoto_maybe_hex(payload: bytes) -> tuple[dict[str, Any], bytes | None]:
    info = _parse_sendphoto(payload)
    if info.get("error"):
        return info, None
    parts = payload.split(b",", 2)
    blob = parts[2]
    try:
        ts = blob.decode("ascii")
        if len(ts) % 2 == 0 and len(ts) > 0 and _hex_re.match(ts):
            return {**info, "encoding": "hex_ascii"}, bytes.fromhex(ts)
    except Exception:
        pass
    return {**info, "encoding": "raw"}, blob


def _parse_beacon(payload: bytes) -> dict[str, Any]:
    t = _text(payload)
    parts = _csv(t)
    d: dict[str, Any] = {"command": "BEACON", "parts": parts, "count": None}
    if len(parts) > 1:
        try:
            d["count"] = int(parts[1])
        except ValueError:
            d["count"] = parts[1]
    if len(parts) > 2:
        d["readings"] = parts[2:]
    return d


def _parse_healthcode_q(_payload: bytes) -> dict[str, Any]:
    return {"command": "HEALTHCODEQ"}


def _parse_jxtk_q(_payload: bytes) -> dict[str, Any]:
    return {"command": "JXTKQ"}


PARSERS: dict[str, Any] = {
    "INIT": _parse_init,
    "LK": _parse_lk,
    "LGZONE": _parse_lgzone,
    "UD": lambda p: _parse_ud_family(p, "UD"),
    "UD2": lambda p: _parse_ud_family(p, "UD2"),
    "AL": lambda p: _parse_ud_family(p, "AL"),
    "GETLOC": _parse_getloc,
    "WT": _parse_wt_request,
    "CLOCKIN": lambda p: _parse_ud_family(p, "CLOCKIN"),
    "CLOCKOUT": lambda p: _parse_ud_family(p, "CLOCKOUT"),
    "JXTK": _parse_jxtk,
    "SENDPHOTO": _parse_sendphoto,
    "BEACON": _parse_beacon,
    "HEALTHCODEQ": _parse_healthcode_q,
    "JXTKQ": _parse_jxtk_q,
}


def parse_command(command: str, payload: bytes) -> tuple[dict[str, Any], bytes | None]:
    """
    返回 (summary_dict, optional_binary_media)。
    SENDPHOTO 返回解码后的字节；JXTK 音频在 summary 中只有长度，二进制由调用方从 payload 再解。
    """
    cmd = command.strip().upper()
    if cmd == "SENDPHOTO":
        meta, blob = _parse_sendphoto_maybe_hex(payload)
        return meta, blob
    if cmd == "JXTK":
        summary = _parse_jxtk(payload)
        parts = payload.split(b",", 5)
        if len(parts) >= 6:
            return summary, unescape_jxtk(parts[5])
        return summary, None
    fn = PARSERS.get(cmd)
    if fn is not None:
        return fn(payload), None
    return _generic(payload), None


def summary_to_json(d: dict[str, Any]) -> str:
    safe: dict[str, Any] = {}
    for k, v in d.items():
        if isinstance(v, (str, int, float, bool)) or v is None:
            safe[k] = v
        elif isinstance(v, list):
            safe[k] = [x if isinstance(x, (str, int, float, bool)) else str(x) for x in v]
        else:
            safe[k] = str(v)
    return json.dumps(safe, ensure_ascii=False)


def hex_preview(data: bytes | None, limit: int = 256) -> str | None:
    if not data:
        return None
    h = data[:limit].hex()
    if len(data) > limit:
        h += "..."
    return h
