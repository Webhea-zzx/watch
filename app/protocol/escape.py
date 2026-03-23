from __future__ import annotations


def unescape_jxtk(data: bytes) -> bytes:
    """JXTK 二进制段转义还原：0x7D 0x01 -> 0x7D 等。"""
    out = bytearray()
    i = 0
    while i < len(data):
        b = data[i]
        if b == 0x7D and i + 1 < len(data):
            n = data[i + 1]
            m = {0x01: 0x7D, 0x02: 0x5B, 0x03: 0x5D, 0x04: 0x2C, 0x05: 0x2A}.get(n)
            if m is not None:
                out.append(m)
                i += 2
                continue
        out.append(b)
        i += 1
    return bytes(out)


def escape_jxtk(data: bytes) -> bytes:
    out = bytearray()
    for b in data:
        if b == 0x7D:
            out.extend(b"\x7d\x01")
        elif b == 0x5B:
            out.extend(b"\x7d\x02")
        elif b == 0x5D:
            out.extend(b"\x7d\x03")
        elif b == 0x2C:
            out.extend(b"\x7d\x04")
        elif b == 0x2A:
            out.extend(b"\x7d\x05")
        else:
            out.append(b)
    return bytes(out)


def unescape_healthcode_param(s: str) -> str:
    """平台 HEALTHCODE 参数中的 \\0 \\1 还原（终端侧一般不需）。"""
    return s.replace("\\0", "\x00").replace("\\1", ",")  # 文档为字面反斜杠序列
