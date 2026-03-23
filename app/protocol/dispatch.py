from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.config import PLATFORM_TZ_OFFSET_HOURS
from app.protocol.framing import ParsedFrame, build_frame
from app.protocol.parsers.registry import parse_command


class OutboundSeq:
    __slots__ = ("_n",)

    def __init__(self) -> None:
        self._n = 0

    def next(self) -> str:
        self._n = (self._n + 1) % 0x10000
        if self._n == 0:
            self._n = 1
        return f"{self._n:04X}"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _lk_reply_payload() -> str:
    t = _utc_now()
    return t.strftime("LK,%Y-%m-%d,%H:%M:%S")


def _lgzone_reply_payload() -> str:
    t = _utc_now() + timedelta(hours=PLATFORM_TZ_OFFSET_HOURS)
    sign = "+" if PLATFORM_TZ_OFFSET_HOURS >= 0 else "-"
    h = abs(PLATFORM_TZ_OFFSET_HOURS)
    return f"LGZONE,{sign}{h},{t.strftime('%H:%M:%S')},{t.strftime('%Y-%m-%d')}"


def _getloc_reply_from_parse(parsed: dict) -> str:
    """根据终端上报的位置字段生成占位回复（未接地图地理编码）。"""
    lat = parsed.get("lat")
    lng = parsed.get("lng")
    lat_dir = parsed.get("lat_dir") or "N"
    lng_dir = parsed.get("lng_dir") or "E"
    u = _utc_now()
    if lat is not None and lng is not None:
        addr = "WGS84,未解析地址"
        return (
            f"GETLOC,{u.strftime('%Y-%m-%d')},{u.strftime('%H:%M:%S')},"
            f"{lat},{lat_dir},{lng},{lng_dir},{addr}"
        )
    return f"GETLOC,{u.strftime('%Y-%m-%d')},{u.strftime('%H:%M:%S')},0,N,0,E,无定位数据"


def _wt_reply_stub() -> str:
    u = _utc_now()
    # 天气描述示例为 GB2312 十六进制，这里用 UTF-8 占位十六进制简化
    desc = "晴".encode("utf-8").hex()
    city = "本地".encode("utf-16-be").hex()
    return (
        f"WT,{u.strftime('%y-%m-%d')},{u.strftime('%H:%M:%S')},"
        f"{desc},0,20,15,25,{city}"
    )


def _healthcode_stub() -> str:
    return "HEALTHCODE,0,20220101000000,,,"


# 终端上报后平台需短确认的指令（文档示例或惯例）
_ACK_SAME_AS_COMMAND = frozenset(
    {
        "UD",
        "AL",
        "HEART",
        "BLOOD",
        "BPHRT",
        "OXYGEN",
        "SLEEP",
        "TEMP",
        "PHOTO",
        "BEACON",
        "BEACONSTART",
        "LKSET",
        "UPLOAD",
        "UDTIME",
        "CR",
        "LZ",
        "IDNAME",
        "POWEROFF",
        "RESET",
        "FIND",
        "REMIND",
        "SIMLOCK",
        "RESETQ",
        "SOS",
        "MONITOR",
        "SETDND",
        "WHITELIST",
        "KEYPAD",
        "SETDWMODE",
        "NOMOVESLP",
        "HRTSTART",
        "HRSETAL",
        "SLEEPTIME",
        "SEDENTARY",
        "HEALTHCODE",
        "TEMPSETAL",
        "TEMPSTART",
        "FDLIST",
        "MESSAGE",
        "JXTKR",
        "VN",
    }
)


def build_replies(frame: ParsedFrame, parsed: dict, seq: OutboundSeq) -> list[bytes]:
    """根据入站帧与解析结果生成待发送的下行字节帧（可能 0 条）。seq 为连接级出站流水号。"""
    cmd = frame.command
    v, d = frame.vendor, frame.device_id

    def one(payload: str) -> bytes:
        return build_frame(v, d, seq.next(), payload)

    if cmd == "UD2":
        return []

    if cmd == "INIT":
        return [one("INIT,1")]

    if cmd == "LGZONE":
        return [one(_lgzone_reply_payload())]

    if cmd == "LK":
        return [one(_lk_reply_payload())]

    if cmd == "GETLOC":
        return [one(_getloc_reply_from_parse(parsed))]

    if cmd == "WT":
        return [one(_wt_reply_stub())]

    if cmd == "JXTK":
        return [one("JXTKR,1")]

    if cmd == "SENDPHOTO":
        return [one("SENDPHOTO")]

    if cmd == "HEALTHCODEQ":
        return [one(_healthcode_stub())]

    if cmd in ("CLOCKIN", "CLOCKOUT"):
        return [one(f"{cmd},1")]

    if cmd in _ACK_SAME_AS_COMMAND:
        return [one(cmd)]

    if cmd == "JXTKQ":
        return [one("VN")]

    if cmd == "MFD":
        peer = ""
        parts = parsed.get("parts") if isinstance(parsed, dict) else None
        if isinstance(parts, list) and len(parts) > 1:
            peer = parts[1]
        return [one(f"MFD,1,{peer},好友,00000000000")]

    if cmd == "DFD":
        return [one("DFD,1")]

    if cmd == "QFD":
        peer = ""
        parts = parsed.get("parts") if isinstance(parsed, dict) else None
        if isinstance(parts, list) and len(parts) > 1:
            peer = parts[1]
        return [one(f"QFD,0,{peer},,")]

    if cmd == "PHB":
        parts = parsed.get("parts") if isinstance(parsed, dict) else None
        sn = "0001"
        if isinstance(parts, list) and len(parts) > 1:
            sn = str(parts[1])
        return [one(f"PHB,{sn},1")]

    if cmd == "SET":
        parts = parsed.get("parts") if isinstance(parsed, dict) else None
        sn = "0001"
        if isinstance(parts, list) and len(parts) > 1:
            sn = str(parts[1])
        return [one(f"SET,{sn},1")]

    if cmd == "SMS":
        return [one("SMS,1")]

    if cmd == "SENDSMS":
        return [one("SENDSMS,1")]

    # 未知指令：回复与指令名相同的一字节确认，避免部分固件阻塞
    if cmd and cmd != "EMPTY":
        return [one(cmd)]
    return []
