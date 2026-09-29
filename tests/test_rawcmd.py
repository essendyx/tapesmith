"""Tests für die Schutzliste `protocol.rawcmd`."""

import pytest

from tapesmith.protocol.rawcmd import classify_raw, parse_hex


def test_parse_hex_accepts_common_formats():
    expected = bytes.fromhex("1f1108")
    assert parse_hex("1F 11 08") == expected
    assert parse_hex("0x1f1108") == expected
    assert parse_hex("1f:11:08") == expected


@pytest.mark.parametrize("text", ["1f1", "zz", ""])
def test_parse_hex_rejects_invalid(text):
    with pytest.raises(ValueError):
        parse_hex(text)


@pytest.mark.parametrize("hex_str,level", [
    ("1f1108", "erlaubt"),
    ("1f11111f1112", "erlaubt"),
    ("1b40", "erlaubt"),
    ("1b640d", "erlaubt"),
    ("1b641f", "rückfrage"),
    ("1b4e0408", "erlaubt"),
    ("1b4e0420", "rückfrage"),
    ("1f110208", "erlaubt"),
    ("1f1199", "rückfrage"),
    ("1f110e05", "rückfrage"),
    ("1d7630000c000100ff", "rückfrage"),
    ("1b370701", "gesperrt"),
    ("001b3702", "gesperrt"),
    ("aabb", "rückfrage"),
])
def test_classify_raw_table(hex_str, level):
    verdict = classify_raw(bytes.fromhex(hex_str))
    assert verdict.level == level
    assert verdict.reason


def test_gesperrt_reason_mentions_escape7():
    verdict = classify_raw(bytes.fromhex("1b370701"))
    assert "ESC 7" in verdict.reason
    assert "Heizparameter" in verdict.reason


def test_known_query_reason_names_akku():
    verdict = classify_raw(bytes.fromhex("1f1108"))
    assert "Akku" in verdict.reason
