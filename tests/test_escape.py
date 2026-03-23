from app.protocol.escape import escape_jxtk, unescape_jxtk


def test_jxtk_roundtrip_star():
    raw = b"a*b[c]d,e\x7d"
    assert unescape_jxtk(escape_jxtk(raw)) == raw


def test_jxtk_unescape_doc_mapping():
    assert unescape_jxtk(bytes([0x7D, 0x05])) == b"*"
