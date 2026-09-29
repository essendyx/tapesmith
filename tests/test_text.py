import pytest
from PIL import Image, ImageDraw

from tapesmith.render.fonts import FontMissing, load_font
from tapesmith.render.text import MIN_SIZE, fit_text, render_text_block

SSD = "pmx10 SSD-1 SN 274913"


def test_single_line_fills_height():
    block = fit_text([SSD], "sans", 88)
    assert block.image.mode == "1"
    assert 80 <= block.image.height <= 88
    assert block.font_size > 60


def test_max_width_limits_size():
    wide = fit_text([SSD], "sans", 88)
    narrow = fit_text([SSD], "sans", 88, max_width=200)
    assert narrow.image.width <= 200 < wide.image.width
    assert narrow.font_size < wide.font_size


def test_two_lines_are_smaller_and_fit():
    one = fit_text(["pmx10 · SSD-1"], "sans", 88)
    two = fit_text(["pmx10 · SSD-1", "SN 274913"], "sans", 88)
    assert two.font_size < one.font_size
    assert two.image.height <= 88


def test_center_alignment_centers_short_line():
    block = render_text_block(["WWWWWW", "i"], "sans", 30, align="center")
    w, h = block.image.size
    lower = block.image.crop((0, h // 2, w, h))
    xs = [x for x in range(w) for y in range(lower.height) if lower.getpixel((x, y)) == 0]
    assert abs((min(xs) + max(xs)) / 2 - w / 2) <= 2


def test_only_pure_black_and_white(pixel_colors):
    block = render_text_block([SSD], "mono", 40)
    assert pixel_colors(block.image) <= {0, 255}
    assert 0 in pixel_colors(block.image)


@pytest.mark.parametrize("size", range(8, 15))
@pytest.mark.parametrize("text", ["gjpqy", "ÄÖÜ", "pmx10 SSD-1"])
def test_no_clipped_pixels_and_no_empty_margin_at_small_sizes(size, text, pixel_counts):
    """Regression: Bei kleinen Groessen darf keine Tinte abgeschnitten werden, und es darf
    keine leere Randzeile/-spalte entstehen. Die Pixelzahl muss der eines Renders auf einer
    grossen (garantiert nicht abschneidenden) Leinwand entsprechen."""
    block = render_text_block([text], "sans", size)
    img = block.image
    w, h = img.size
    top_row = [img.getpixel((x, 0)) for x in range(w)]
    bottom_row = [img.getpixel((x, h - 1)) for x in range(w)]
    left_col = [img.getpixel((0, y)) for y in range(h)]
    right_col = [img.getpixel((w - 1, y)) for y in range(h)]
    assert 0 in top_row, f"obere Randzeile ist leer bei Groesse {size}, Text {text!r}"
    assert 0 in bottom_row, f"untere Randzeile ist leer bei Groesse {size}, Text {text!r}"
    assert 0 in left_col, f"linke Randspalte ist leer bei Groesse {size}, Text {text!r}"
    assert 0 in right_col, f"rechte Randspalte ist leer bei Groesse {size}, Text {text!r}"

    font = load_font("sans", size)
    ascent, _descent = font.getmetrics()
    big = Image.new("1", (2000, 2000), 0)
    draw = ImageDraw.Draw(big)
    draw.fontmode = "1"
    draw.text((500, 500 + ascent), text, font=font, fill=255, anchor="ls")
    expected_ink = pixel_counts(big).get(255, 0)
    actual_ink = pixel_counts(img).get(0, 0)
    assert actual_ink == expected_ink


def test_errors():
    with pytest.raises(FontMissing):
        fit_text([SSD], "comic", 88)
    with pytest.raises(ValueError, match="passt nicht"):
        fit_text(["X" * 400], "sans", 88, max_width=50)
    with pytest.raises(ValueError, match="kein Text"):
        fit_text(["", "  "], "sans", 88)
    with pytest.raises(ValueError, match="Ausrichtung"):
        render_text_block([SSD], "sans", 20, align="justify")
    assert MIN_SIZE == 6
