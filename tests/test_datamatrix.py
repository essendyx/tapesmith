import pytest
import zxingcpp
from PIL import Image

from tapesmith.render.datamatrix import datamatrix_matrix, render_datamatrix


def test_render_datamatrix_square_no_warning():
    data = "S4EWNX0R123456789012"
    n = len(datamatrix_matrix(data))
    r = render_datamatrix(data, 88)
    assert r.image.width == r.image.height
    assert r.module_dots == 88 // n
    assert r.decodes
    assert r.warnings == ()

    quiet = 20
    canvas = Image.new("L", (r.image.width + 2 * quiet, r.image.height + 2 * quiet), 255)
    canvas.paste(r.image.convert("L"), (quiet, quiet))
    results = zxingcpp.read_barcodes(canvas, formats=zxingcpp.BarcodeFormat.DataMatrix)
    assert any(res.text == data for res in results)


def test_render_datamatrix_fixed_module_width():
    data = "112233274913"
    n = len(datamatrix_matrix(data))
    r = render_datamatrix(data, 88, module=3)
    assert r.image.width == 3 * n


def test_render_datamatrix_too_long_raises():
    with pytest.raises(ValueError, match="passt nicht lesbar"):
        render_datamatrix("x" * 120, 40)


def test_render_datamatrix_module_two_warns():
    data = "112233274913"
    n = len(datamatrix_matrix(data))
    r = render_datamatrix(data, 2 * n, module=2)
    assert r.module_dots == 2
    assert any("nur 2 Punkte" in w for w in r.warnings)


def test_render_datamatrix_empty_content():
    with pytest.raises(ValueError, match="ohne Inhalt"):
        render_datamatrix("", 88)
