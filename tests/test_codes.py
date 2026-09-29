from tapesmith.render.barcode import render_code128
from tapesmith.render.codes import invert_with_quiet, self_test_code
import zxingcpp


def test_invert_with_quiet_default_canvas():
    r = render_code128("ASN01234", 3, 88)
    bars = r.image.crop((0, 0, r.image.width, 50))
    out, ok = invert_with_quiet(bars, 4)
    assert ok is True
    assert out.size == (bars.width + 8, bars.height + 8)
    px = out.load()
    ow, oh = out.size
    ring = ([px[x, 0] for x in range(ow)] + [px[x, oh - 1] for x in range(ow)]
            + [px[0, y] for y in range(oh)] + [px[ow - 1, y] for y in range(oh)])
    assert set(ring) == {0}

    bars_px = bars.load()
    inner_px = out.load()
    was_black = [(x, y) for x in range(bars.width) for y in range(bars.height) if bars_px[x, y] == 0]
    assert was_black
    for x, y in was_black[:50]:
        assert inner_px[x + 4, y + 4] == 255


def test_invert_with_quiet_small_canvas_reports_false():
    r = render_code128("ASN01234", 3, 88)
    bars = r.image.crop((0, 0, r.image.width, 50))
    canvas = (bars.width + 2, bars.height + 2)
    out, ok = invert_with_quiet(bars, 4, canvas=canvas)
    assert out.size == canvas
    assert ok is False


def test_self_test_code_detects_broken_barcode():
    r = render_code128("ASN01234", 3, 88)
    bars = r.image.crop((0, 0, r.image.width, 50)).copy()
    w, h = bars.size
    broken = bars.copy()
    broken.paste(255, (w // 4, 0, w // 4 + w // 2, h))
    quiet = 30
    assert self_test_code(bars, "ASN01234", zxingcpp.BarcodeFormat.Code128, quiet)
    assert not self_test_code(broken, "ASN01234", zxingcpp.BarcodeFormat.Code128, quiet)
