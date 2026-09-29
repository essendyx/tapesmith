import pytest

from tapesmith.render.shapes import draw_line, draw_rect, warning_stripes


def test_draw_line_horizontal_thickness():
    img = draw_line(40, 10, "h", 2)
    assert img.size == (40, 10) and img.mode == "1"
    px = img.load()
    black_rows = {y for y in range(10) if px[0, y] == 0}
    assert black_rows == {4, 5}


def test_draw_line_horizontal_dash():
    img = draw_line(40, 10, "h", 2, dash=5)
    px = img.load()
    row = 4
    cols = [1 if px[x, row] == 0 else 0 for x in range(15)]
    assert cols == [1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1]


def test_draw_line_arrow_end():
    w, h = 60, 20
    img = draw_line(w, h, "h", 2, arrow_end=True)
    px = img.load()
    tip_rows = {y for y in range(h) if px[w - 1, y] == 0}
    assert tip_rows & {9, 10}
    base_col_count = sum(1 for y in range(h) if px[55, y] == 0)
    assert base_col_count > 2


def test_draw_rect_border_and_center():
    img = draw_rect(30, 20, 2)
    px = img.load()
    assert px[0, 0] == 0
    assert px[15, 10] == 255


def test_draw_rect_solid_fill():
    img = draw_rect(30, 20, 2, fill="solid")
    assert set(c for _, c in img.getcolors()) == {0}


def test_draw_rect_stripes_fill():
    img = draw_rect(30, 20, 0, fill="stripes", stripe=4)
    px = img.load()
    assert px[0, 0] == 0
    assert px[4, 0] == 255


def test_warning_stripes_pattern():
    img = warning_stripes(20, 8, stripe=4)
    px = img.load()
    assert px[0, 0] == 0
    assert px[4, 0] == 255


@pytest.mark.parametrize("call", [
    lambda: draw_line(17, 23, "v", 3),
    lambda: draw_line(17, 23, "down", 2),
    lambda: draw_line(17, 23, "up", 2),
    lambda: draw_rect(17, 23, 2, radius=3),
    lambda: warning_stripes(17, 23),
])
def test_shapes_exact_size_and_mode(call):
    img = call()
    assert img.size == (17, 23)
    assert img.mode == "1"
