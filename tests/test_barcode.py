import pytest
import zxingcpp
from PIL import Image

from tapesmith.render import barcode
from tapesmith.render.barcode import code128_modules, code128_width, render_code128
from tapesmith.render.text import render_text_block

DATA = "ASN01234"


def test_code128_modules_start_stop():
    modules = code128_modules(DATA)
    assert modules.startswith("11010010000") or modules.startswith("11010011100")
    assert modules.endswith("1100011101011")


def test_render_code128_size_and_warning():
    r2 = render_code128(DATA, 2, 88)
    assert r2.image.size == (code128_width(DATA, 2), 88)
    assert r2.decodes
    assert any("2 Punkte" in w for w in r2.warnings)

    r3 = render_code128(DATA, 3, 88)
    assert r3.warnings == ()


def test_render_code128_independent_rereading():
    r = render_code128(DATA, 3, 88)
    bar_area = r.image.crop((0, 0, r.image.width, 50))
    quiet = 20
    canvas = Image.new("L", (bar_area.width + 2 * quiet, bar_area.height + 2 * quiet), 255)
    canvas.paste(bar_area.convert("L"), (quiet, quiet))
    results = zxingcpp.read_barcodes(canvas, formats=zxingcpp.BarcodeFormat.Code128)
    assert any(res.text == DATA for res in results)


def test_render_code128_no_text():
    r = render_code128(DATA, 2, 88, show_text=False)
    px = r.image.load()
    bottom_row = r.image.height - 1
    assert any(px[x, bottom_row] == 0 for x in range(r.image.width))


@pytest.mark.parametrize("kwargs, message_part", [
    ({"module": 1}, "mindestens 2 Punkte"),
    ({"data": ""}, "ohne Inhalt"),
    ({"data": "Größe ä"}, "nur ASCII"),
    ({"max_width": 50}, "verfügbar 50"),
    ({"height": 20}, "zu niedrig"),
])
def test_render_code128_errors(kwargs, message_part):
    params = {"data": DATA, "module": 3, "height": 88}
    params.update(kwargs)
    with pytest.raises(ValueError, match=message_part):
        render_code128(params.pop("data"), params.pop("module"), params.pop("height"), **params)


def test_render_code128_text_size_clamped_to_max(monkeypatch):
    def fake_fit_text(lines, font, max_height, max_width=None, align="left"):
        return render_text_block(lines, font, 30, align)

    monkeypatch.setattr(barcode, "fit_text", fake_fit_text)
    r = render_code128(DATA, 3, 200)
    expected_height = render_text_block([DATA], "mono", barcode.TEXT_MAX_SIZE, "center").image.height
    expected_bar_height = 200 - expected_height - barcode.TEXT_GAP_DOTS
    px = r.image.load()
    # Zeile direkt unterhalb des Balkenbereichs (Abstand) muss weiss sein, die Zeile davor
    # (letzte Balkenzeile) kann Tinte enthalten, so laesst sich die tatsaechliche Balkenhoehe
    # (und damit die gekappte Texthoehe) am Bild ablesen.
    gap_row = expected_bar_height
    assert all(px[x, gap_row] == 255 for x in range(r.image.width))
    assert r.image.height == 200
    assert r.decodes


def test_render_code128_text_size_warns_when_tiny(monkeypatch):
    def fake_fit_text(lines, font, max_height, max_width=None, align="left"):
        return render_text_block(lines, font, 8, align)

    monkeypatch.setattr(barcode, "fit_text", fake_fit_text)
    r = render_code128(DATA, 3, 200)
    assert any("sehr klein" in w for w in r.warnings)


def test_render_code128_without_fake_is_tall_and_decodes():
    r = render_code128(DATA, 3, 200)
    assert r.image.height == 200
    assert r.decodes
