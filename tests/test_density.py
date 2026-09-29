"""Tests für den Dichte-Kalibrierassistenten (experimentell)."""

import pytest
import zxingcpp
from PIL import ImageOps

from tapesmith.density import density_candidates, density_test_head
from tapesmith.device.profile import load_profile
from tapesmith.render.compose import mm_to_rows
from tapesmith.tape.profiles import find_tape, save_tape_density


def test_density_candidates_m110():
    candidates = density_candidates("m110", (3, 8))
    assert [c.command for c in candidates] == [bytes.fromhex("1b4e0403"), bytes.fromhex("1b4e0408")]
    assert [c.label for c in candidates] == ["#1 M110 n=3", "#2 M110 n=8"]


def test_density_candidates_m02():
    candidates = density_candidates("m02", (8,))
    assert candidates[0].command == bytes.fromhex("1f110208")


def test_density_candidates_rejects_unknown_family():
    with pytest.raises(ValueError):
        density_candidates("x")


@pytest.mark.parametrize("value", [0, 16])
def test_density_candidates_rejects_out_of_range_value(value):
    with pytest.raises(ValueError):
        density_candidates("m110", (value,))


def test_density_candidates_rejects_too_many_values():
    with pytest.raises(ValueError):
        density_candidates("m110", tuple(range(1, 8)))


def test_density_test_head_dimensions_and_content(pixel_colors):
    profile = load_profile()
    candidate = density_candidates("m110", (8,))[0]
    head = density_test_head(candidate, profile)
    assert head.width == profile.head_dots
    assert head.height == mm_to_rows(45.0, profile)
    colors = pixel_colors(head)
    assert 0 in colors  # schwarze Punkte vorhanden
    assert 255 in colors  # weiße Punkte vorhanden


def test_density_test_head_checkerboard_is_roughly_half_black(pixel_counts):
    profile = load_profile()
    candidate = density_candidates("m110", (8,))[0]
    head = density_test_head(candidate, profile)
    # Zone 2 (Graufläche) liegt ungefähr im zweiten Fünftel der Länge.
    top = round(head.height * 0.22)
    bottom = round(head.height * 0.35)
    crop = head.crop((profile.content_offset, top, profile.content_offset + profile.content_dots, bottom))
    counts = pixel_counts(crop)
    black = counts.get(0, 0)
    total = crop.width * crop.height
    assert 0.35 < black / total < 0.65


def test_density_test_head_outside_content_area_is_white():
    profile = load_profile()
    candidate = density_candidates("m110", (8,))[0]
    head = density_test_head(candidate, profile)
    left = head.crop((0, 0, profile.content_offset, head.height))
    assert ImageOps.invert(left.convert("L")).getbbox() is None
    right_start = profile.content_offset + profile.content_dots
    if right_start < head.width:
        right = head.crop((right_start, 0, head.width, head.height))
        assert ImageOps.invert(right.convert("L")).getbbox() is None


def test_density_test_head_qr_decodes_to_p12():
    profile = load_profile()
    candidate = density_candidates("m110", (8,))[0]
    head = density_test_head(candidate, profile)
    expanded = ImageOps.expand(head.convert("L"), border=24, fill=255)
    results = zxingcpp.read_barcodes(expanded)
    assert any(r.text == "P12" for r in results)


def test_density_test_head_too_short_raises():
    profile = load_profile()
    candidate = density_candidates("m110", (8,))[0]
    with pytest.raises(ValueError, match="35"):
        density_test_head(candidate, profile, length_mm=30)


def test_save_tape_density_sets_and_reads_back():
    tape = save_tape_density("weiss-schwarz", 8, "m110")
    assert tape.density == 8
    assert tape.density_family == "m110"
    assert tape.name == "Weiß auf Schwarz"
    assert tape.background == (25, 25, 25)

    reloaded = find_tape("weiss-schwarz")
    assert reloaded.density == 8
    assert reloaded.density_family == "m110"


def test_save_tape_density_none_removes_both():
    save_tape_density("weiss-schwarz", 8, "m110")
    tape = save_tape_density("weiss-schwarz", None, None)
    assert tape.density is None
    assert tape.density_family is None


def test_save_tape_density_unknown_tape_raises():
    with pytest.raises(ValueError):
        save_tape_density("gibtsnicht", 8, "m110")


def test_invalid_density_family_in_user_file_raises(app_home):
    from tapesmith.tape.profiles import user_tapes_path
    import json

    user_path = user_tapes_path()
    user_path.write_text(json.dumps([
        {"id": "x", "name": "x", "background": [255, 255, 255], "ink": [0, 0, 0],
         "density": 5, "density_family": "kaputt"},
    ]), encoding="utf-8")
    with pytest.raises(ValueError):
        find_tape("x")
