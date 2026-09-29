import dataclasses
import json

import pytest

from tapesmith.device.profile import CALIBRATION_KEYS, load_profile, save_calibration
from tapesmith.protocol.status import DEFAULT_CODES


def test_p12_defaults_match_soburi():
    p = load_profile()
    assert p.model == "P12"
    assert p.head_dots == 96
    assert p.bytes_per_line == 12
    assert p.content_dots == 88
    assert p.content_offset == 8
    assert p.response_timeout_s == 2.0
    assert p.init_packets == (
        bytes.fromhex("1f1138"),
        bytes.fromhex("1f11111f11121f11091f1113"),
        bytes.fromhex("1f1109"),
        bytes.fromhex("1f11191f1111"),
        bytes.fromhex("1f1119"),
        bytes.fromhex("1f1107"),
    )
    assert p.feed_command == bytes.fromhex("1b640d1b640d")
    assert p.verified == ("battery", "lid", "media", "serial", "firmware")
    assert p.trailer_mm == 16.0
    assert p.leader_mm == 8.0


def test_status_codes_are_hashable_and_build_map():
    p = load_profile()
    hash(p)  # darf nicht werfen (status_codes ist ein Tupel aus Tripeln)
    codes = p.status_map()
    assert codes["lid"] == {0x99: "offen", 0x98: "zu"}
    assert codes["paper"] == {0x88: "leer", 0x89: "ok"}
    assert codes["media"] == {0x0B: "endlos", 0x26: "Marken"}


def test_status_map_without_status_codes_falls_back_to_default():
    p = dataclasses.replace(load_profile(), status_codes=())
    assert p.status_map() == {kind: dict(codes) for kind, codes in DEFAULT_CODES.items()}


def test_invalid_status_code_hex_key_raises_value_error(tmp_path):
    cal = tmp_path / "calibration.json"
    cal.write_text(json.dumps({"status_codes": {"lid": {"zz": "offen"}}}), encoding="utf-8")
    with pytest.raises(ValueError, match="calibration.json"):
        load_profile(calibration_path=cal)


def test_save_calibration_leaves_no_tmp_files(tmp_path):
    cal = tmp_path / "calibration.json"
    save_calibration(cal, trailer_mm=16.0)
    assert list(tmp_path.glob("*.tmp")) == []


def test_calibration_overlay(tmp_path):
    cal = tmp_path / "calibration.json"
    save_calibration(cal, content_offset=6, content_dots=84)
    save_calibration(cal, leader_mm=7.5)
    assert json.loads(cal.read_text(encoding="utf-8")) == {
        "content_offset": 6, "content_dots": 84, "leader_mm": 7.5}
    p = load_profile(calibration_path=cal)
    assert (p.content_offset, p.content_dots, p.leader_mm) == (6, 84, 7.5)


def test_calibration_rejects_unknown_key(tmp_path):
    with pytest.raises(KeyError):
        save_calibration(tmp_path / "c.json", head_dots=128)


def test_invalid_geometry_is_rejected(tmp_path):
    cal = tmp_path / "calibration.json"
    save_calibration(cal, content_offset=20, content_dots=88)
    with pytest.raises(ValueError, match="passt nicht"):
        load_profile(calibration_path=cal)


def test_incomplete_profile_json_becomes_value_error(monkeypatch):
    import tapesmith.device.profile as profile_mod

    class FakeFile:
        def joinpath(self, name):
            return self

        def read_text(self, encoding="utf-8"):
            return json.dumps({"model": "P12", "head_dots": 96})  # unvollstaendig

    monkeypatch.setattr(profile_mod.resources, "files", lambda pkg: FakeFile())
    with pytest.raises(ValueError, match="p12.json"):
        profile_mod.load_profile()


def test_calibration_keys_are_profile_fields():
    p = load_profile()
    for key in CALIBRATION_KEYS:
        assert hasattr(p, key)
