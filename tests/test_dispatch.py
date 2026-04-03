from app.protocol.dispatch import OutboundSeq, build_replies
from app.protocol.framing import ParsedFrame


def test_init_reply():
    f = ParsedFrame("ZJ", "5678901234", "0001", b"INIT,13800000000,0,v1,0001,0001")
    seq = OutboundSeq()
    reps = build_replies(f, {}, seq)
    assert len(reps) == 1
    assert reps[0].startswith(b"[ZJ*5678901234*")
    assert reps[0].endswith(b"INIT,1]")


def test_ud2_no_reply():
    f = ParsedFrame("ZJ", "1", "0001", b"UD2,1")
    reps = build_replies(f, {}, OutboundSeq())
    assert reps == []


def test_setdwmode_uplink_no_reply_avoids_ack_loop():
    f = ParsedFrame("ZJ", "1", "0001", b"SETDWMODE,1")
    reps = build_replies(f, {}, OutboundSeq())
    assert reps == []


def test_upload_uplink_no_reply_avoids_ack_loop():
    f = ParsedFrame("ZJ", "1", "0001", b"UPLOAD,600")
    reps = build_replies(f, {}, OutboundSeq())
    assert reps == []


def test_lk_reply_contains_lk():
    f = ParsedFrame("ZJ", "1", "0001", b"LK,1,0,100")
    reps = build_replies(f, {}, OutboundSeq())
    assert len(reps) == 1
    assert b"LK," in reps[0]


def test_outbound_seq_increments_after_reply():
    f = ParsedFrame("ZJ", "1", "0001", b"INIT,1,0,v,0,0")
    seq = OutboundSeq()
    build_replies(f, {}, seq)
    assert seq.next() == "0002"
