"""将协议帧 / 解析结果转为面向客户的中文短句（列表、详情、宏共用逻辑）。"""

from __future__ import annotations

from app.protocol.framing import FrameBuffer
from app.protocol.parsers.registry import parse_command

_DATA_TYPE_CN: dict[str, str] = {
    "INIT": "首次联网登记",
    "LGZONE": "校时请求",
    "LK": "心跳（步数、电量）",
    "LKSET": "心跳间隔设置",
    "UD": "定位",
    "UD2": "补传定位",
    "AL": "报警 / 求救",
    "GETLOC": "查询位置描述",
    "WT": "天气请求",
    "CR": "立即定位",
    "HEART": "心率",
    "BLOOD": "血压",
    "BPHRT": "心率与血压",
    "OXYGEN": "血氧",
    "SLEEP": "睡眠",
    "TEMP": "体温",
    "SMS": "短信内容上报",
    "JXTK": "语音微聊",
    "JXTKQ": "语音微聊查询",
    "SENDPHOTO": "照片",
    "BEACON": "蓝牙信标",
    "CLOCKIN": "上班打卡",
    "CLOCKOUT": "下班打卡",
    "HEALTHCODEQ": "健康码请求",
    "EMPTY": "空指令",
}


def data_type_label(cmd: str) -> str:
    c = (cmd or "").strip().upper()
    if not c:
        return "其它数据"
    return _DATA_TYPE_CN.get(c, f"指令「{c}」")


def _clip(s: str, n: int = 48) -> str:
    s = (s or "").strip()
    if len(s) <= n:
        return s
    return s[: n - 1] + "…"


def summary_from_parsed(cmd: str, d: dict) -> str:
    """由 parse_command 的 summary dict 生成一行中文说明。"""
    c = (cmd or "").strip().upper()
    parts = d.get("parts")
    if not isinstance(parts, list):
        parts = []

    if c == "LK":
        steps = d.get("steps")
        bat = d.get("battery")
        if steps is not None and bat is not None:
            return f"步数约 {steps}，电量 {bat}%"
        if bat is not None:
            return f"电量 {bat}%"
        return "已收到心跳数据"

    if c in ("UD", "UD2", "AL"):
        rev = (d.get("reverse_address") or "").strip()
        lat, lng = d.get("lat"), d.get("lng")
        if rev:
            if lat is not None and lng is not None:
                return f"{rev}（纬度 {lat}，经度 {lng}）"
            return rev
        if lat is not None and lng is not None:
            return f"纬度 {lat}，经度 {lng}（可在地图查看）"
        return "已收到定位相关信息（可能为基站或 WiFi，未含经纬度）"

    if c == "INIT":
        fw = d.get("firmware")
        if fw:
            return f"系统版本：{_clip(str(fw), 64)}"
        return "手表已登记到系统"

    if c == "HEART":
        if len(parts) > 1:
            return f"心率约 {parts[1]} 次/分钟"
        return "已收到心率数据"

    if c == "BLOOD":
        if len(parts) > 2:
            return f"收缩压 {parts[1]}，舒张压 {parts[2]}"
        return "已收到血压数据"

    if c == "OXYGEN":
        if len(parts) > 1:
            return f"血氧约 {parts[1]}%"
        return "已收到血氧数据"

    if c == "TEMP":
        if len(parts) > 1:
            return f"体温相关数值：{parts[1]}"
        return "已收到体温数据"

    if c == "SENDPHOTO":
        if d.get("declared_size") is not None:
            return f"照片大小约 {d['declared_size']} 字节，已保存附件"
        return "已收到照片"

    if c == "JXTK":
        if d.get("audio_size") is not None:
            return f"语音片段约 {d['audio_size']} 字节，已保存附件"
        return "已收到语音数据"

    if c == "BEACON":
        cnt = d.get("count")
        base = "蓝牙信标"
        if cnt is not None:
            base += f"，约 {cnt} 条读数"
        if isinstance(d.get("readings"), list) and d["readings"]:
            prev = "，".join(_clip(str(x), 24) for x in d["readings"][:3])
            return f"{base}：{prev}"
        return base + "信息已记录"

    if c == "LGZONE":
        return "手表请求与服务器校时"

    if c == "HEALTHCODEQ":
        return "健康码相关请求"

    if c == "JXTKQ":
        return "语音微聊能力查询"

    if c in ("WT", "GETLOC", "CR", "CLOCKIN", "CLOCKOUT"):
        label = data_type_label(c)
        rev = (d.get("reverse_address") or "").strip()
        if rev:
            return f"{label}：{rev}"
        if len(parts) > 3:
            tail = "，".join(_clip(str(x), 32) for x in parts[1:5] if str(x))
            return f"{label}：{tail}" if tail else f"已收到「{label}」数据"
        return f"已收到「{label}」数据"

    # 通用：类型名 + 前几项参数，避免「已记录」无信息量
    label = data_type_label(c)
    if len(parts) > 1:
        tail = "，".join(_clip(str(x), 40) for x in parts[1:8] if str(x).strip())
        if tail:
            return f"{label}：{tail}"
    return f"已收到「{label}」数据"


def summarize_raw_frame(raw_frame: str, direction: str = "in") -> str:
    """
    从入库的整帧文本生成一行中文。direction 为 out 时前缀说明为服务器侧。
    """
    raw = raw_frame or ""
    prefix = ""
    if (direction or "").lower() == "out":
        prefix = "服务器回复 · "

    if not raw.strip():
        return prefix + "无正文"

    try:
        data = raw.encode("latin-1")
    except UnicodeEncodeError:
        data = raw.encode("utf-8", errors="replace")

    buf = FrameBuffer()
    buf.feed(data)
    frames = list(buf.extract_frames())
    if not frames:
        snippet = _clip(" ".join(raw.split()), 140)
        return prefix + (f"原始内容（未拆出完整协议帧）：{snippet}" if snippet else "未能解析为完整协议帧")

    pl = frames[0].payload
    cmd = frames[0].command
    summary, _ = parse_command(cmd, pl)
    body = summary_from_parsed(cmd, summary)
    return prefix + body
