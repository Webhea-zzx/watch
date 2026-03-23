from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterator

# 单帧指令内容最大字节数（含 JXTK/SENDPHOTO）；防止恶意超大长度
MAX_PAYLOAD_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class ParsedFrame:
    vendor: str
    device_id: str
    seq: str
    payload: bytes

    @property
    def payload_text(self) -> str:
        try:
            return self.payload.decode("utf-8")
        except UnicodeDecodeError:
            return self.payload.decode("latin-1")

    @property
    def command(self) -> str:
        text = self.payload_text
        if "," in text:
            return text.split(",", 1)[0].strip().upper()
        return text.strip().upper() or "EMPTY"


_SEQ_RE = re.compile(r"^[0-9A-Fa-f]{4}$")
_LEN_RE = re.compile(r"^[0-9A-Fa-f]{4}$")


def _read_until_star(data: bytes, start: int) -> tuple[str | None, int]:
    i = start
    while i < len(data):
        b = data[i]
        if b == ord("*"):
            return data[start:i].decode("ascii", errors="replace"), i + 1
        if b < 32 or b > 126:
            return None, start
        i += 1
    return None, start


def build_frame(
    vendor: str,
    device_id: str,
    seq: str | int,
    payload: str | bytes,
) -> bytes:
    """组装一帧平台下发报文。seq 为 4 位十六进制字符串或 0–65535 整数。"""
    if isinstance(seq, int):
        if not 0 <= seq <= 0xFFFF:
            raise ValueError("seq out of range")
        seq_str = f"{seq:04X}"
    else:
        seq_str = seq.upper()
        if not _SEQ_RE.match(seq_str):
            raise ValueError("seq must be 4 hex digits")
    payload_b = payload.encode("utf-8") if isinstance(payload, str) else payload
    if len(payload_b) > 65535:
        raise ValueError("payload too large")
    len_hex = f"{len(payload_b):04X}"
    header = f"{vendor}*{device_id}*{seq_str}*{len_hex}*".encode("ascii")
    return b"[" + header + payload_b + b"]"


class FrameBuffer:
    """累积 TCP 字节流，按协议拆出完整帧。"""

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, data: bytes) -> None:
        if data:
            self._buf.extend(data)

    def extract_frames(self) -> Iterator[ParsedFrame]:
        while True:
            frame = self._try_extract_one()
            if frame is None:
                break
            yield frame

    def _try_extract_one(self) -> ParsedFrame | None:
        data = self._buf
        start = data.find(ord("["))
        if start < 0:
            data.clear()
            return None
        if start > 0:
            del data[:start]

        # 需要至少 [v*d*s*l*
        pos = 1
        vendor, pos = _read_until_star(data, pos)
        if vendor is None:
            return None
        device_id, pos = _read_until_star(data, pos)
        if device_id is None:
            return None
        seq, pos = _read_until_star(data, pos)
        if seq is None:
            return None
        seq = seq.upper()
        if not _SEQ_RE.match(seq):
            del data[0:1]
            return self._try_extract_one()
        len_hex, pos = _read_until_star(data, pos)
        if len_hex is None:
            return None
        len_hex = len_hex.upper()
        if not _LEN_RE.match(len_hex):
            del data[0:1]
            return self._try_extract_one()
        plen = int(len_hex, 16)
        if plen > MAX_PAYLOAD_BYTES:
            del data[0:1]
            return self._try_extract_one()
        end_payload = pos + plen
        if end_payload + 1 > len(data):
            return None
        if data[end_payload] != ord("]"):
            del data[0:1]
            return self._try_extract_one()
        payload = bytes(data[pos:end_payload])
        frame = ParsedFrame(
            vendor=vendor,
            device_id=device_id,
            seq=seq,
            payload=payload,
        )
        del data[: end_payload + 1]
        return frame


def frame_to_bytes(frame: ParsedFrame) -> bytes:
    """将解析结果还原为线路上一帧（用于审计入库）。"""
    return build_frame(frame.vendor, frame.device_id, frame.seq, frame.payload)
