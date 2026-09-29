"""Tests für die Farbvorschau nach Band (tape.preview)."""

from PIL import Image

from tapesmith.tape.preview import CHECKER, CHECKER_SIZE, colorize, tape_colors
from tapesmith.tape.profiles import find_tape


def _bild_4x2_links_schwarz_rechts_weiss() -> Image.Image:
    img = Image.new("L", (4, 2), 255)
    for y in range(2):
        for x in range(2):
            img.putpixel((x, y), 0)
    return img.convert("1")


def test_tape_colors_none_ist_schwarz_weiss():
    background, ink = tape_colors(None)
    assert background == (255, 255, 255)
    assert ink == (0, 0, 0)


def test_colorize_none_entspricht_schwarz_weiss():
    img = _bild_4x2_links_schwarz_rechts_weiss()
    result = colorize(img, None)
    assert result.getpixel((0, 0)) == (0, 0, 0)
    assert result.getpixel((2, 0)) == (255, 255, 255)


def test_colorize_gold_schwarz():
    img = _bild_4x2_links_schwarz_rechts_weiss()
    gold_schwarz = find_tape("gold-schwarz")
    result = colorize(img, gold_schwarz)
    assert result.getpixel((0, 0)) == (212, 175, 55)   # Tinte -> Druckfarbe
    assert result.getpixel((2, 0)) == (25, 25, 25)      # weiß im Original -> Bandfarbe


def test_colorize_transparent_zeigt_schachbrett():
    img = _bild_4x2_links_schwarz_rechts_weiss()
    transparent = find_tape("schwarz-transparent")
    result = colorize(img, transparent, checker=1)

    weisse_pixel = {result.getpixel((x, y)) for x in (2, 3) for y in (0, 1)}
    assert weisse_pixel == set(CHECKER)

    schwarze_pixel = {result.getpixel((x, y)) for x in (0, 1) for y in (0, 1)}
    assert schwarze_pixel == {transparent.ink}


def test_colorize_default_checker_size_konstant():
    assert CHECKER_SIZE == 4
