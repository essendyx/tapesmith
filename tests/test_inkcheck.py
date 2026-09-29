from PIL import Image

from tapesmith.device.profile import load_profile
from tapesmith.render.compose import LabelSpec, render_label
from tapesmith.render.inkcheck import ink_stats, ink_warnings

PROFILE = load_profile()


def test_ink_stats_full_black():
    head = Image.new("1", (96, 100), 0)
    stats = ink_stats(head)
    assert stats.job_ratio == 1.0
    assert stats.heavy_rows == 100
    assert stats.max_row_ratio == 1.0


def test_ink_stats_full_white():
    head = Image.new("1", (96, 100), 255)
    stats = ink_stats(head)
    assert stats.job_ratio == 0.0
    assert stats.heavy_rows == 0


def test_ink_warnings_unknown_battery():
    head = Image.new("1", (96, 100), 0)
    warnings = ink_warnings([head], None)
    assert len(warnings) == 1
    assert "unbekanntem Akkustand" in warnings[0]


def test_ink_warnings_battery_ok_no_warning():
    head = Image.new("1", (96, 100), 0)
    assert ink_warnings([head], 80) == []


def test_ink_warnings_low_battery_named():
    head = Image.new("1", (96, 100), 0)
    warnings = ink_warnings([head], 20)
    assert any("Akku 20 %" in w for w in warnings)


def test_ink_warnings_special_battery_code_treated_unknown():
    head = Image.new("1", (96, 100), 0)
    warnings = ink_warnings([head], 255)
    assert warnings and "unbekanntem Akkustand" in warnings[0]


def test_ink_warnings_normal_label_no_warning():
    result = render_label(LabelSpec(lines=("pmx10",)), PROFILE)
    assert ink_warnings([result.head], None) == []
