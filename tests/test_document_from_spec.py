import dataclasses

import pytest
import segno
import zxingcpp
from PIL import Image, ImageChops, ImageOps

from tapesmith.device.profile import load_profile
from tapesmith.document.from_spec import spec_to_document
from tapesmith.document.model import bbox, find_object, replace_object
from tapesmith.document.render import render_document, render_spec
from tapesmith.render.compose import LabelSpec, mm_to_rows, render_label
from tapesmith.render.qr import QUIET_MODULES
from tapesmith.tape.profiles import find_tape

PROFILE = load_profile()

MATRIX = [
    LabelSpec(lines=("pmx10 SSD-1", "SN 274913")),
    LabelSpec(lines=("pmx10 SSD-1", "SN 274913"), max_length_mm=40),
    LabelSpec(lines=("pmx10 SSD-1", "SN 274913"), fixed_length_mm=60, align="left"),
    LabelSpec(lines=("pmx10 SSD-1", "SN 274913"), fixed_length_mm=60, align="center"),
    LabelSpec(lines=("pmx10 SSD-1", "SN 274913"), fixed_length_mm=60, align="right"),
    LabelSpec(lines=("pmx10 SSD-1", "SN 274913"), font="mono", font_size=30),
    LabelSpec(qr="112233274913"),
    LabelSpec(lines=("pmx10 SSD-1", "SN 274913"), qr="112233274913"),
    LabelSpec(lines=("Backup",), font="sans-bold"),
]

QR_SPEC = LabelSpec(lines=("pmx10 · SSD-1", "SN 123456"), qr="S4EWNX0R123456")


@pytest.mark.parametrize("spec", MATRIX, ids=range(len(MATRIX)))
def test_pixelgleich_zu_render_label(spec):
    expected = render_label(spec, PROFILE)
    doc = spec_to_document(spec, PROFILE)
    dr = render_document(doc, PROFILE)
    assert dr.ok, dr.errors
    assert dr.landscape.size == expected.landscape.size
    assert ImageChops.difference(expected.landscape.convert("L"), dr.landscape.convert("L")).getbbox() is None
    assert dr.head.tobytes() == expected.head.tobytes()
    assert doc.length_mode == "fixed"
    assert mm_to_rows(doc.length_mm, PROFILE) == expected.landscape.width


def test_objekte_der_kurzform():
    spec = MATRIX[7]
    doc = spec_to_document(spec, PROFILE)
    qr = find_object(doc, "qr1")
    text = find_object(doc, "text1")
    ref = render_label(spec, PROFILE)
    assert qr.module == ref.qr.module_dots and qr.error == spec.qr_error
    assert qr.w == qr.h == ref.qr.image.width
    assert text.size == ref.font_size and text.text == "pmx10 SSD-1\nSN 274913"
    assert text.valign == "middle" and text.align == spec.align


@pytest.mark.parametrize("spec", [
    LabelSpec(lines=("ein sehr langer Text für ein kurzes Label",), fixed_length_mm=5),
    LabelSpec(lines=("ein sehr langer Text",), fixed_length_mm=20, font_size=60),
    LabelSpec(lines=("Text",), qr="112233274913", fixed_length_mm=8),
    LabelSpec(),
    LabelSpec(lines=("  ",)),
], ids=range(5))
def test_gleiche_fehler_wie_render_label(spec):
    with pytest.raises(ValueError) as expected:
        render_label(spec, PROFILE)
    with pytest.raises(ValueError) as actual:
        spec_to_document(spec, PROFILE)
    assert str(actual.value) == str(expected.value)


@pytest.mark.parametrize("tape", [None, "schwarz-weiss"])
def test_render_spec_helles_band_bytegleich(tape):
    t = None if tape is None else find_tape(tape)
    for spec in (QR_SPEC, MATRIX[0]):
        expected = render_label(spec, PROFILE)
        result = render_spec(spec, PROFILE, t)
        assert result.head.tobytes() == expected.head.tobytes()
        assert result.warnings == expected.warnings


def test_render_spec_warn_haengt_warnung_an():
    tape = dataclasses.replace(find_tape("weiss-schwarz"), code_mode="warn")
    expected = render_label(QR_SPEC, PROFILE)
    result = render_spec(QR_SPEC, PROFILE, tape)
    assert result.head.tobytes() == expected.head.tobytes()
    assert any("viele Scanner" in w for w in result.warnings)


def test_render_spec_ohne_qr_auf_dunklem_band_unveraendert():
    expected = render_label(MATRIX[0], PROFILE)
    result = render_spec(MATRIX[0], PROFILE, find_tape("weiss-schwarz"))
    assert result.head.tobytes() == expected.head.tobytes()


def _reads_on_dark_band(landscape: Image.Image, box_x1: int) -> list[str]:
    look = ImageOps.invert(landscape.convert("L"))
    canvas = Image.new("L", (look.width + 80, look.height + 80), 0)
    canvas.paste(look, (40, 40))
    crop = canvas.crop((0, 0, min(canvas.width, box_x1 + 40 + 40), canvas.height))
    return [r.text for r in zxingcpp.read_barcodes(crop)]


def _qr_box(doc):
    return bbox(find_object(doc, "qr1"))


def test_render_spec_invertiert_auf_dunklem_band():
    tape = find_tape("weiss-schwarz")
    normal = render_label(QR_SPEC, PROFILE)
    result = render_spec(QR_SPEC, PROFILE, tape)
    assert result.head.tobytes() != normal.head.tobytes()
    assert not any("unvollständig" in w for w in result.warnings)
    assert not any("Ruhezone" in w for w in result.warnings)
    doc = spec_to_document(QR_SPEC, PROFILE, invert_codes=True)
    assert "S4EWNX0R123456" in _reads_on_dark_band(result.landscape, _qr_box(doc)[2])


def test_gegenprobe_ohne_ruhezone_nicht_lesbar():
    tape = find_tape("weiss-schwarz")
    doc = spec_to_document(QR_SPEC, PROFILE, invert_codes=True)
    qr = find_object(doc, "qr1")
    n = len(segno.make_qr(QR_SPEC.qr, error=QR_SPEC.qr_error, boost_error=False).matrix)
    size = n * qr.module
    quiet = QUIET_MODULES * qr.module
    tight = dataclasses.replace(qr, x=qr.x + quiet, y=(88 - size) // 2, w=size, h=size)
    doc2 = replace_object(doc, tight)
    dr = render_document(doc2, PROFILE, tape=tape)
    assert any("Ruhezone auf dunklem Band unvollständig" in i.message for i in dr.warnings)
    assert "S4EWNX0R123456" not in _reads_on_dark_band(dr.landscape, bbox(tight)[2])


def test_invert_pfad_box():
    doc = spec_to_document(QR_SPEC, PROFILE, invert_codes=True)
    qr = find_object(doc, "qr1")
    n = len(segno.make_qr(QR_SPEC.qr, error=QR_SPEC.qr_error, boost_error=False).matrix)
    assert qr.module == 88 // (n + 4) == 3
    assert qr.y == 0 and qr.h == 88
    assert qr.w == n * qr.module + 2 * QUIET_MODULES * qr.module
    length = mm_to_rows(doc.length_mm, PROFILE)
    assert qr.x >= 0 and qr.x + qr.w <= length
    text = find_object(doc, "text1")
    assert text.x >= qr.x + qr.w


def test_invert_pfad_ohne_qr_wie_normal():
    spec = MATRIX[0]
    assert spec_to_document(spec, PROFILE, invert_codes=True) == spec_to_document(spec, PROFILE)


def test_version2_nur_zwei_module():
    spec = dataclasses.replace(QR_SPEC, qr="SN S4EWNX0R123456789012")
    assert len(segno.make_qr(spec.qr, error="m", boost_error=False).matrix) == 25
    result = render_spec(spec, PROFILE, find_tape("weiss-schwarz"))
    assert any("Ruhezone auf dunklem Band nur 2 Module" in w for w in result.warnings)
    doc = spec_to_document(spec, PROFILE, invert_codes=True)
    assert spec.qr in _reads_on_dark_band(result.landscape, _qr_box(doc)[2])


def _first_ink_column(landscape: Image.Image, start: int) -> int:
    for col in range(start, landscape.width):
        if landscape.crop((col, 0, col + 1, landscape.height)).getextrema()[0] == 0:
            return col
    return landscape.width


@pytest.mark.parametrize("spec", [
    QR_SPEC,
    LabelSpec(lines=("pmx10",), qr="S4EWNX0R123456"),
    dataclasses.replace(QR_SPEC, fixed_length_mm=60, align="left"),
], ids=["qr-text", "qr-kurz", "fest-60"])
def test_invert_pfad_luecke_zwischen_ruhezone_und_text(spec):
    """Dunkles Band: zwischen gedruckter Ruhezone und dem ersten Textstrich bleibt ungedruckter Abstand."""
    tape = find_tape("weiss-schwarz")
    doc = spec_to_document(spec, PROFILE, invert_codes=True)
    box_x1 = _qr_box(doc)[2]
    result = render_spec(spec, PROFILE, tape)
    land = result.landscape.convert("1")
    # letzte Box-Spalte ist gedruckt (helle Ruhezone), danach bleibt eine Lücke von mindestens 1 mm
    assert land.crop((box_x1 - 1, 0, box_x1, land.height)).getextrema() == (0, 0)
    gap = _first_ink_column(land, box_x1) - box_x1
    assert gap >= mm_to_rows(1.0, PROFILE)
    assert gap >= QUIET_MODULES * find_object(doc, "qr1").module
    assert _first_ink_column(land, box_x1) < land.width
