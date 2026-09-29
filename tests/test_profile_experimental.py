"""Tests für Profilerweiterungen (block_rows, experimental)."""

import json

import pytest

from tapesmith.device.profile import EXPERIMENTAL_FLAGS, load_profile, save_calibration


def test_defaults_are_off():
    p = load_profile()
    assert p.block_rows == 0
    assert p.experimental == ()


def test_calibration_sets_block_rows_and_experimental(tmp_path):
    cal = tmp_path / "calibration.json"
    cal.write_text(json.dumps({"block_rows": 255, "experimental": ["usb"]}), encoding="utf-8")
    p = load_profile(calibration_path=cal)
    assert p.block_rows == 255
    assert p.experimental == ("usb",)
    assert EXPERIMENTAL_FLAGS == ("usb",)


def test_block_rows_out_of_range_raises(tmp_path):
    cal = tmp_path / "calibration.json"
    cal.write_text(json.dumps({"block_rows": 300}), encoding="utf-8")
    with pytest.raises(ValueError, match="block_rows"):
        load_profile(calibration_path=cal)


def test_unknown_experimental_flag_raises(tmp_path):
    cal = tmp_path / "calibration.json"
    cal.write_text(json.dumps({"experimental": ["xyz"]}), encoding="utf-8")
    with pytest.raises(ValueError, match="xyz"):
        load_profile(calibration_path=cal)


def test_save_calibration_allows_block_rows(tmp_path):
    cal = tmp_path / "calibration.json"
    save_calibration(cal, block_rows=0)
    assert json.loads(cal.read_text(encoding="utf-8")) == {"block_rows": 0}
    p = load_profile(calibration_path=cal)
    assert p.block_rows == 0
