from tapesmith.device.profile import load_profile
from tapesmith.protocol.status import decode


def kinds(buf):
    return [(m.kind, m.value) for m in decode(buf)]


def test_known_single_byte_messages():
    assert kinds(bytes.fromhex("1a045a")) == [("battery", 90)]
    assert kinds(bytes.fromhex("1a0598")) == [("lid", "offen")]
    assert kinds(bytes.fromhex("1a0599")) == [("lid", "zu")]
    assert kinds(bytes.fromhex("1a0688")) == [("paper", "leer")]
    assert kinds(bytes.fromhex("1a0600")) == [("paper", "ok")]
    assert kinds(bytes.fromhex("1a0c0b")) == [("media", "endlos")]
    assert kinds(bytes.fromhex("1a090a")) == [("auto_off", 10)]
    assert kinds(bytes.fromhex("1a03a9")) == [("overheat", 0xA9)]


def test_firmware_three_bytes_and_serial_ascii():
    msgs = decode(bytes.fromhex("1a07010203") + b"\x1a\x08P12ABC" + bytes.fromhex("1a0599"))
    assert [(m.kind, m.value) for m in msgs] == [("firmware", "1.2.3"), ("serial", "P12ABC"), ("lid", "zu")]


def test_unknown_and_garbage_are_kept():
    msgs = decode(bytes.fromhex("ff1a7701"))
    assert msgs[0].kind == "unknown" and msgs[0].raw == b"\xff"
    assert msgs[1].kind == "unknown" and msgs[1].raw == bytes.fromhex("1a7701")


def test_empty_and_truncated():
    assert decode(b"") == []
    assert decode(b"\x1a")[0].kind == "unknown"


def test_serial_backslashreplace_avoids_replacement_char():
    msgs = decode(b"\x1a\x08P12\xff")
    assert msgs[0].kind == "serial"
    assert "�" not in msgs[0].value
    assert msgs[0].value == "P12\\xff"


def test_truncated_firmware():
    msgs = decode(bytes.fromhex("1a070102"))
    assert len(msgs) == 1
    assert msgs[0].kind == "unknown"
    assert msgs[0].raw == bytes.fromhex("1a070102")
    assert msgs[0].text.startswith("abgeschnitten")

    msgs = decode(bytes.fromhex("1a0599") + bytes.fromhex("1a0701"))
    assert [(m.kind, m.value) for m in msgs] == [("lid", "zu"), ("unknown", None)]


def test_p12_codes_invert_lid():
    codes = load_profile().status_map()
    assert [(m.kind, m.value) for m in decode(bytes.fromhex("1a0599"), codes)] == [("lid", "offen")]
    assert [(m.kind, m.value) for m in decode(bytes.fromhex("1a0598"), codes)] == [("lid", "zu")]
    assert [(m.kind, m.value) for m in decode(bytes.fromhex("1a0689"), codes)] == [("paper", "ok")]
