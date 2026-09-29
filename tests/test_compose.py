import dataclasses

import pytest

from tapesmith.device.profile import load_profile
from tapesmith.render.compose import LabelSpec, mm_to_rows, preview_image, render_label, rows_to_mm

P = load_profile()
SSD = "pmx10 SSD-1 SN 274913"


def test_text_label_geometry():
    r = render_label(LabelSpec(lines=(SSD,)), P)
    assert r.landscape.mode == "1" and r.landscape.height == P.content_dots
    assert r.head.width == P.head_dots and r.head.height == r.landscape.width
    assert r.length_mm == pytest.approx(r.landscape.width / 8)
    assert r.tape_mm == pytest.approx(r.length_mm + 24)
    assert r.warnings == []
    assert r.font_size and r.font_size > 60


def test_margin_is_white(pixel_colors):
    r = render_label(LabelSpec(lines=(SSD,)), P)
    margin = mm_to_rows(1.0, P)
    left = r.landscape.crop((0, 0, margin, r.landscape.height))
    assert pixel_colors(left) == {255}


def test_trailing_margin_is_white(pixel_colors):
    r = render_label(LabelSpec(lines=(SSD,)), P)
    margin = mm_to_rows(1.0, P)
    right = r.landscape.crop((r.landscape.width - margin, 0, r.landscape.width, r.landscape.height))
    assert pixel_colors(right) == {255}


def test_fixed_length_and_length_factor():
    assert render_label(LabelSpec(lines=("SSD-1",), fixed_length_mm=20), P).landscape.width == 160
    stretched = dataclasses.replace(P, length_factor=1.1)
    assert mm_to_rows(20, stretched) == 176
    assert rows_to_mm(176, stretched) == pytest.approx(20)


def test_max_length_shrinks_text():
    free = render_label(LabelSpec(lines=(SSD,)), P)
    limited = render_label(LabelSpec(lines=(SSD,), max_length_mm=20), P)
    assert limited.landscape.width <= 160
    assert limited.font_size < free.font_size


def test_fixed_font_that_does_not_fit_raises():
    with pytest.raises(ValueError, match="passt nicht"):
        render_label(LabelSpec(lines=("A" * 50,), font_size=40, fixed_length_mm=10), P)


def test_qr_plus_text(pixel_colors):
    r = render_label(LabelSpec(lines=("SN 274913",), qr="S4EWNX0R123456"), P)
    assert r.qr is not None and r.qr.decodes
    quiet = 4 * r.qr.module_dots
    assert pixel_colors(r.landscape.crop((0, 0, quiet, P.content_dots))) == {255}
    assert 0 in pixel_colors(r.landscape.crop((quiet, 0, quiet + r.qr.image.width, P.content_dots)))


def test_warnings_small_and_long():
    small = render_label(LabelSpec(lines=("WWWWWWWWWW",), max_length_mm=10), P)
    assert any("klein" in w for w in small.warnings)
    long = render_label(LabelSpec(lines=("X" * 40,), font_size=80), P)
    assert any("lang" in w for w in long.warnings)


def test_nothing_to_print_raises():
    with pytest.raises(ValueError, match="Nichts zu drucken"):
        render_label(LabelSpec(lines=("", " ")), P)


def test_preview_is_scaled_with_tape_margins():
    r = render_label(LabelSpec(lines=("SSD-1",)), P)
    img = preview_image(r, scale=2)
    lead = mm_to_rows(P.leader_mm, P)
    trail = mm_to_rows(P.trailer_mm, P)
    assert img.mode == "L"
    assert img.width == (r.landscape.width + lead + trail) * 2
    assert img.height == P.head_dots * 2


def test_qr_only_too_long_for_fixed_length_raises():
    with pytest.raises(ValueError, match="passt nicht"):
        render_label(LabelSpec(qr="HTTP://L.LAN/D7", fixed_length_mm=5), P)
    with pytest.raises(ValueError, match="passt nicht"):
        render_label(LabelSpec(qr="HTTP://L.LAN/D7", max_length_mm=5), P)


def test_align_positions_whole_content_block_at_fixed_length():
    def ink_bounds(img):
        cols = [x for x in range(img.width) if 0 in [img.getpixel((x, y)) for y in range(img.height)]]
        return min(cols), max(cols)

    left = render_label(LabelSpec(lines=("SSD-1",), fixed_length_mm=30, align="left"), P)
    center = render_label(LabelSpec(lines=("SSD-1",), fixed_length_mm=30, align="center"), P)
    right = render_label(LabelSpec(lines=("SSD-1",), fixed_length_mm=30, align="right"), P)
    assert left.landscape.width == center.landscape.width == right.landscape.width

    l0, l1 = ink_bounds(left.landscape)
    c0, c1 = ink_bounds(center.landscape)
    r0, r1 = ink_bounds(right.landscape)
    assert l0 < c0 < r0
    assert l1 < c1 < r1
    margin = mm_to_rows(1.0, P)
    assert l0 == margin
    assert right.landscape.width - 1 - r1 == margin


def test_preview_content_top_matches_head_offset():
    r = render_label(LabelSpec(lines=("SSD-1",)), P)
    assert r.content_top == P.head_dots - P.content_offset - P.content_dots

    P2 = dataclasses.replace(P, content_offset=4)
    r2 = render_label(LabelSpec(lines=("SSD-1",)), P2)
    assert r2.content_top == P2.head_dots - P2.content_offset - P2.content_dots == 4
    img = preview_image(r2, scale=1)
    lead = mm_to_rows(P2.leader_mm, P2)
    xcol = lead + r2.landscape.width // 2
    for y in range(0, r2.content_top):
        assert img.getpixel((xcol, y)) == 200
    for y in range(r2.content_top + P2.content_dots, P2.head_dots):
        assert img.getpixel((xcol, y)) == 200
    assert any(img.getpixel((xcol, y)) != 200
               for y in range(r2.content_top, r2.content_top + P2.content_dots))


def test_preview_uses_leader_and_trailer():
    P2 = dataclasses.replace(P, leader_mm=8.0, trailer_mm=4.0)
    r = render_label(LabelSpec(lines=("SSD-1",)), P2)
    img = preview_image(r, scale=1)
    assert img.width == r.landscape.width + 64 + 32
    assert img.getpixel((63, 0)) == 200
    assert img.getpixel((64 + r.landscape.width + 31, 0)) == 200
    assert r.trail_rows == 32
