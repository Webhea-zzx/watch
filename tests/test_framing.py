import pytest

from app.protocol.framing import FrameBuffer, ParsedFrame, build_frame


def test_build_frame_doc_lk():
    b = build_frame("ZJ", "5678901234", "0001", "LK,100")
    assert b == b"[ZJ*5678901234*0001*0006*LK,100]"


def test_parse_doc_examples():
    buf = FrameBuffer()
    buf.feed(b"[ZJ*5678901234*0001*0006*LK,100]")
    frames = list(buf.extract_frames())
    assert len(frames) == 1
    f = frames[0]
    assert f.vendor == "ZJ"
    assert f.device_id == "5678901234"
    assert f.seq == "0001"
    assert f.payload == b"LK,100"


def test_parse_payload_with_star_escaped_length():
    # 模拟 JXTK：payload 内含 * 的字节，长度字段必须正确
    inner = b"JXTK,0,file.bin,1,1,\x7d\x05"  # escaped *
    frame = build_frame("ZJ", "1", "0002", inner)
    buf = FrameBuffer()
    buf.feed(frame)
    out = list(buf.extract_frames())[0]
    assert out.payload == inner


def test_partial_then_rest():
    buf = FrameBuffer()
    buf.feed(b"[ZJ*5678901234*0001*0006*LK")
    assert list(buf.extract_frames()) == []
    buf.feed(b",100]")
    frames = list(buf.extract_frames())
    assert len(frames) == 1
    assert frames[0].payload == b"LK,100"


def test_utf8_payload_length():
    payload = "MESSAGE," + "你好".encode("utf-16-be").hex()  # wrong - MESSAGE uses unicode hex
    # build with unicode in payload
    p = "MESSAGE,4f60597d"
    f = build_frame("ZJ", "5678901234", 1, p)
    buf = FrameBuffer()
    buf.feed(f)
    assert list(buf.extract_frames())[0].payload.decode() == p
