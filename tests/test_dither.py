import pytest
from PIL import Image

from tapesmith.render.dither import fit_image, to_1bit


def _gradient(w=256, h=8):
    img = Image.new("L", (w, h))
    px = img.load()
    for x in range(w):
        for y in range(h):
            px[x, y] = x
    return img


def test_fit_image_keep_aspect():
    src = Image.new("L", (200, 100), 128)
    fitted = fit_image(src, 88, 88)
    assert fitted.size == (88, 88)
    assert fitted.mode == "L"
    top_row = [fitted.getpixel((x, 0)) for x in range(88)]
    assert all(v == 255 for v in top_row)


def test_fit_image_stretch_without_aspect():
    src = Image.new("L", (200, 100), 0)
    fitted = fit_image(src, 88, 88, keep_aspect=False)
    assert fitted.size == (88, 88)


def test_fit_image_transparent_becomes_white():
    src = Image.new("RGBA", (10, 10), (0, 0, 0, 255))
    px = src.load()
    for x in range(5):
        for y in range(10):
            px[x, y] = (0, 0, 0, 0)
    fitted = fit_image(src, 10, 10, keep_aspect=False)
    for x in range(5):
        for y in range(10):
            assert fitted.getpixel((x, y)) == 255


def test_to_1bit_threshold_none():
    grad = _gradient()
    result = to_1bit(grad, threshold=128)
    assert result.mode == "1"
    px = result.load()
    left = {px[x, 0] for x in range(128)}
    right = {px[x, 0] for x in range(128, 256)}
    assert left == {0}
    assert right == {255}


def test_to_1bit_floyd_ratio():
    grad = _gradient()
    result = to_1bit(grad, dither="floyd")
    black = sum(1 for x in range(256) for y in range(8) if result.getpixel((x, y)) == 0)
    ratio = black / (256 * 8)
    assert 0.4 <= ratio <= 0.6


def test_to_1bit_bayer_ratio_and_deterministic():
    grad = _gradient()
    result1 = to_1bit(grad, dither="bayer")
    result2 = to_1bit(grad, dither="bayer")
    black = sum(1 for x in range(256) for y in range(8) if result1.getpixel((x, y)) == 0)
    ratio = black / (256 * 8)
    assert 0.4 <= ratio <= 0.6
    assert result1.tobytes() == result2.tobytes()


def test_to_1bit_invert():
    grad = _gradient()
    normal = to_1bit(grad, threshold=128)
    inverted = to_1bit(grad, threshold=128, invert=True)
    assert normal.getpixel((0, 0)) != inverted.getpixel((0, 0))
    assert normal.getpixel((255, 0)) != inverted.getpixel((255, 0))


def test_to_1bit_unknown_dither_raises():
    grad = _gradient()
    with pytest.raises(ValueError):
        to_1bit(grad, dither="unknown")
