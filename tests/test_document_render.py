import dataclasses

import pytest
import zxingcpp
from PIL import Image, ImageChops

from tapesmith.device.profile import load_profile
from tapesmith.document.model import (Code128Object, DataMatrixObject, IconObject, ImageObject,
                                     LabelDocument, LineObject, QrObject, RectObject, TextObject,
                                     prepare_embedded_image)
from tapesmith.document.render import (CodeInfo, DocumentRender, ObjectRender, render_document,
                                      render_object, to_render_result)
from tapesmith.render.compose import LabelSpec, mm_to_rows, render_label
from tapesmith.tape.profiles import find_tape

PROFILE = load_profile()
DARK = find_tape("weiss-schwarz")


def doc(*objects, **kwargs) -> LabelDocument:
    return LabelDocument(objects=tuple(objects), **kwargs)


def same(a: Image.Image, b: Image.Image) -> bool:
    return a.size == b.size and ImageChops.difference(a.convert("L"), b.convert("L")).getbbox() is None


def ink_bbox(image: Image.Image):
    return ImageChops.invert(image.convert("L")).getbbox()


def black_share(image: Image.Image, pixel_counts) -> float:
    counts = pixel_counts(image.convert("L"))
    return counts.get(0, 0) / (image.width * image.height)


def gradient_png() -> str:
    return prepare_embedded_image(Image.linear_gradient("L").resize((64, 64)))


# --- Text -------------------------------------------------------------------

def test_text_autofit_in_box():
    t = TextObject(id="t", x=10, y=14, w=200, h=60, text="pmx10 SSD")
    dr = render_document(doc(t), PROFILE)
    assert dr.ok
    assert dr.font_sizes["t"] >= 16
    box = ink_bbox(dr.landscape)
    assert box[0] >= 10 and box[1] >= 14 and box[2] <= 210 and box[3] <= 74
    assert dr.boxes["t"] == (10, 14, 210, 74)


def test_text_invertiert_deckt_ab(pixel_counts):
    below = RectObject(id="r", x=0, y=0, w=200, h=88, fill="solid", thickness=0)
    t = TextObject(id="t", x=20, y=10, w=120, h=60, text="AB", invert=True)
    ro = render_object(t, PROFILE)
    assert ro.opaque and ro.image.size == (120, 60)
    assert black_share(ro.image, pixel_counts) > 0.5
    assert 255 in {v for _c, v in ro.image.getcolors()}
    dr = render_document(doc(below, t), PROFILE)
    # Weißer Text aus dem invertierten Objekt bleibt über dem schwarzen Rahmen sichtbar.
    region = dr.landscape.crop((20, 10, 140, 70))
    assert same(region, ro.image)


def test_drehung_und_spiegelung():
    t90 = TextObject(id="t", x=0, y=0, w=40, h=150, text="AB", rotation=90, align="center")
    r90 = render_object(t90, PROFILE)
    assert r90.image.size == (40, 150)
    assert r90.issues == ()
    base = TextObject(id="t", x=0, y=0, w=150, h=40, text="AB", align="center")
    r0 = render_object(base, PROFILE).image
    assert same(r90.image, r0.transpose(Image.Transpose.ROTATE_270))
    r180 = render_object(dataclasses.replace(base, rotation=180), PROFILE).image
    assert same(r180, r0.transpose(Image.Transpose.ROTATE_180))
    rm = render_object(dataclasses.replace(base, mirror=True), PROFILE).image
    assert same(rm, r0.transpose(Image.Transpose.FLIP_LEFT_RIGHT))
    assert not same(rm, r0)


def _row_blocks(image: Image.Image) -> list[tuple[int, int]]:
    inv = ImageChops.invert(image.convert("L"))
    blocks, start = [], None
    for y in range(image.height):
        has_ink = inv.crop((0, y, image.width, y + 1)).getbbox() is not None
        if has_ink and start is None:
            start = y
        elif not has_ink and start is not None:
            blocks.append((start, y))
            start = None
    if start is not None:
        blocks.append((start, image.height))
    return blocks


def test_senkrechter_text():
    t = TextObject(id="t", x=0, y=0, w=30, h=88, text="SSD", vertical=True)
    ro = render_object(t, PROFILE)
    assert ro.issues == ()
    assert ro.font_size >= 16
    assert ro.image.size == (30, 88)
    assert len(_row_blocks(ro.image)) == 3


def test_senkrechter_text_passt_nicht():
    t = TextObject(id="t", x=0, y=0, w=4, h=10, text="SSD", vertical=True)
    ro = render_object(t, PROFILE)
    assert [i.level for i in ro.issues] == ["error"]
    assert "passt nicht" in ro.issues[0].message


def test_feste_schrift_zu_gross_fehler_aber_gezeichnet():
    t = TextObject(id="t", x=0, y=0, w=40, h=20, text="Groß", size=60)
    ro = render_object(t, PROFILE)
    assert ro.issues[0].level == "error"
    assert ro.issues[0].message == "Text größer als die Box (Schrift 60)"
    assert ink_bbox(ro.image) is not None


def test_kleine_schrift_warnung():
    t = TextObject(id="t", x=0, y=0, w=100, h=8, text="klein")
    ro = render_object(t, PROFILE)
    assert ro.font_size < 16
    assert any(i.level == "warning" and "Schrift sehr klein" in i.message for i in ro.issues)


# --- Codes ------------------------------------------------------------------

def _read(landscape: Image.Image, box, pad=30) -> list[str]:
    x0, y0, x1, y1 = box
    crop = landscape.convert("L").crop((x0, max(0, y0), x1, min(landscape.height, y1)))
    canvas = Image.new("L", (crop.width + 2 * pad, crop.height + 2 * pad), 255)
    canvas.paste(crop, (pad, pad))
    return [r.text for r in zxingcpp.read_barcodes(canvas)]


def test_codes_lesbar():
    q = QrObject(id="qr1", x=10, y=0, w=88, h=88, data="112233274913", module=3)
    c = Code128Object(id="code1", x=120, y=0, w=250, h=88, data="ASN01234")
    d = DataMatrixObject(id="dm1", x=400, y=0, w=88, h=88, data="SN274913")
    dr = render_document(doc(q, c, d), PROFILE)
    assert dr.ok, dr.errors
    for oid, text in (("qr1", "112233274913"), ("code1", "ASN01234"), ("dm1", "SN274913")):
        info = dr.codes[oid]
        assert isinstance(info, CodeInfo)
        assert info.decodes and not info.inverted
        assert text in _read(dr.landscape, dr.boxes[oid])
    assert dr.codes["qr1"].kind == "qr" and dr.codes["qr1"].module_dots == 3
    assert dr.codes["qr1"].version == 1
    assert dr.codes["code1"].kind == "code128" and dr.codes["dm1"].kind == "datamatrix"


def test_qr_ohne_inhalt_und_zu_klein():
    ro = render_object(QrObject(id="q", x=0, y=0, w=88, h=88, data=""), PROFILE)
    assert ro.issues[0].message == "QR ohne Inhalt" and ro.issues[0].object_id == "q"
    ro = render_object(QrObject(id="q", x=0, y=0, w=40, h=40, data="112233274913", module=3), PROFILE)
    assert ro.issues[0].level == "error"
    assert ro.issues[0].message == "QR passt nicht in die Box (braucht 63 Punkte)"
    assert ink_bbox(ro.image) is None and not ro.opaque


def test_code128_zu_schmal():
    c = Code128Object(id="code1", x=0, y=0, w=60, h=88, data="ASN01234")
    dr = render_document(doc(c), PROFILE)
    assert not dr.ok
    assert dr.errors[0].object_id == "code1"
    with pytest.raises(ValueError, match="code1:"):
        to_render_result(dr, PROFILE)


# --- Icon, Formen, Bild ------------------------------------------------------

def test_icon_linie_rahmen_bild():
    objs = (
        IconObject(id="icon1", x=0, y=0, w=88, h=88, icon="tabler:server"),
        LineObject(id="line1", x=90, y=0, w=80, h=88, direction="h", thickness=3, arrow_end=True),
        RectObject(id="rect1", x=180, y=0, w=80, h=88, fill="stripes"),
        ImageObject(id="image1", x=270, y=0, w=88, h=88, png=gradient_png(), dither="floyd"),
    )
    dr = render_document(doc(*objs), PROFILE)
    assert dr.ok, dr.errors
    assert dr.warnings == ()
    for obj in objs:
        assert ink_bbox(dr.landscape.crop(dr.boxes[obj.id])) is not None


def test_icon_fehlt():
    ro = render_object(IconObject(id="i", x=0, y=0, w=40, h=40, icon="tabler:gibtsnicht-xyz"), PROFILE)
    assert ro.issues[0].level == "error"


def test_ein_punkt_linie_warnung():
    ro = render_object(LineObject(id="l", x=0, y=0, w=50, h=10, thickness=1), PROFILE)
    assert [(i.level, i.message) for i in ro.issues] == [
        ("warning", "1-Punkt-Linie kann bei hellem Druck verschwinden")]
    ro = render_object(RectObject(id="r", x=0, y=0, w=50, h=10, thickness=1), PROFILE)
    assert ro.issues[0].message == "1-Punkt-Linie kann bei hellem Druck verschwinden"
    assert not ro.opaque
    assert render_object(RectObject(id="r", x=0, y=0, w=50, h=10, fill="solid"), PROFILE).opaque


def test_nicht_deckend_nur_schwarz(pixel_colors):
    rect = RectObject(id="r", x=0, y=0, w=100, h=88, fill="solid", thickness=0)
    frame = RectObject(id="f", x=0, y=0, w=100, h=88, thickness=2)
    dr = render_document(doc(rect, frame), PROFILE)
    # Der nicht deckende Rahmen darf die schwarze Fläche darunter nicht weiß überschreiben.
    assert pixel_colors(dr.landscape.crop((0, 0, 100, 88))) == {0}


# --- Länge und Prüfungen -------------------------------------------------------

def _text(**kw):
    base = dict(id="t", x=0, y=0, w=300, h=88, text="Viel Inhalt hier")
    base.update(kw)
    return TextObject(**base)


def test_laenge_auto_fixed_max():
    t = _text(w=120)
    dr = render_document(doc(t), PROFILE)
    assert dr.length_rows == 120 + mm_to_rows(1.0, PROFILE)
    dr = render_document(doc(t, length_mode="fixed", length_mm=40), PROFILE)
    assert dr.length_rows == mm_to_rows(40, PROFILE)
    assert dr.landscape.size == (mm_to_rows(40, PROFILE), 88)
    dr = render_document(doc(_text(), length_mode="max", length_mm=20), PROFILE)
    assert not dr.ok
    assert "passt nicht in 20 mm" in dr.errors[0].message
    assert dr.errors[0].object_id is None
    assert dr.length_rows == 300 + mm_to_rows(1.0, PROFILE)


def test_ragt_heraus_und_unsichtbar():
    t = _text(y=-5, w=100)
    hidden = _text(id="h", x=150, w=50, visible=False)
    over = _text(id="o", x=-3, w=50)
    dr = render_document(doc(t, hidden, over), PROFILE)
    msgs = [(i.object_id, i.message) for i in dr.warnings]
    assert ("t", "Objekt ragt aus dem druckbaren Bereich (quer)") in msgs
    assert ("o", "Objekt ragt über den Labelrand") in msgs
    assert "h" not in dr.boxes
    assert dr.length_rows == 100 + mm_to_rows(1.0, PROFILE)


def test_langes_label_warnung():
    dr = render_document(doc(_text(w=50), length_mode="fixed", length_mm=250), PROFILE)
    assert any(i.object_id is None and i.message == "Label ungewöhnlich lang (250 mm)" for i in dr.warnings)


def test_ganzes_label_spiegeln_und_drehen():
    t = _text(w=150, align="left")
    plain = render_document(doc(t), PROFILE).landscape
    mirrored = render_document(doc(t, mirror=True), PROFILE).landscape
    assert same(mirrored, plain.transpose(Image.Transpose.FLIP_LEFT_RIGHT))
    rotated = render_document(doc(t, rotate180=True), PROFILE).landscape
    assert same(rotated, plain.transpose(Image.Transpose.ROTATE_180))


def test_leeres_dokument():
    dr = render_document(doc(), PROFILE)
    assert not dr.ok
    assert dr.errors[0].message == "Nichts zu drucken"
    assert dr.landscape.size == (1, 88)


def test_leerer_text():
    empty = TextObject(id="leer", x=0, y=0, w=100, h=40, text="")
    t = TextObject(id="t", x=110, y=0, w=100, h=88, text="pmx10")
    dr = render_document(doc(empty, t), PROFILE)
    assert dr.ok
    assert ("leer", "Text ist leer, nicht gedruckt") in [(i.object_id, i.message) for i in dr.warnings]
    assert "leer" in dr.boxes and "leer" not in dr.font_sizes
    to_render_result(dr, PROFILE)
    ro = render_object(empty, PROFILE)
    assert not ro.opaque and ro.font_size is None
    dr = render_document(doc(TextObject(id="t", x=0, y=0, w=100, h=40, text="  ")), PROFILE)
    assert [i.message for i in dr.errors] == ["Nichts zu drucken"]


# --- Dunkles Band -----------------------------------------------------------------

def test_n20_qr_invertiert(pixel_colors):
    q = QrObject(id="qr1", x=0, y=0, w=87, h=88, data="112233274913", module=3)
    dr = render_document(doc(q), PROFILE, tape=DARK)
    assert dr.codes["qr1"].inverted
    assert not any("Ruhezone" in i.message for i in dr.issues)
    land = dr.landscape
    for strip in ((0, 0, 12, 88), (75, 0, 87, 88), (0, 0, 87, 12), (0, 76, 87, 88)):
        assert pixel_colors(land.crop(strip)) == {0}
    dr = render_document(doc(dataclasses.replace(q, w=63, h=63)), PROFILE, tape=DARK)
    assert any(i.message == "Ruhezone auf dunklem Band unvollständig, Box vergrößern" for i in dr.warnings)


def test_n20_warn_modus():
    tape = dataclasses.replace(DARK, code_mode="warn")
    q = QrObject(id="qr1", x=0, y=0, w=88, h=88, data="112233274913")
    dr = render_document(doc(q), PROFILE, tape=tape)
    assert not dr.codes["qr1"].inverted
    assert any("viele Scanner" in i.message for i in dr.warnings)


def test_n20_datamatrix_und_code128():
    d = DataMatrixObject(id="dm1", x=0, y=0, w=88, h=88, data="SN274913", module=4)
    ro = render_object(d, PROFILE, tape=DARK)
    assert ro.opaque and ro.code.inverted
    c = Code128Object(id="c", x=0, y=0, w=300, h=88, data="ASN01234")
    ro = render_object(c, PROFILE, tape=DARK)
    assert ro.opaque and ro.code.inverted
    assert ro.image.size == (300, 88)


# --- RenderResult ----------------------------------------------------------------

def test_to_render_result_wie_render_label():
    ref = render_label(LabelSpec(lines=("pmx10",), fixed_length_mm=40), PROFILE)
    dr = render_document(doc(_text(w=100, text="pmx10"), length_mode="fixed", length_mm=40), PROFILE)
    assert isinstance(dr, DocumentRender)
    rr = to_render_result(dr, PROFILE)
    assert (rr.lead_rows, rr.trail_rows, rr.content_top) == (ref.lead_rows, ref.trail_rows, ref.content_top)
    assert rr.tape_mm == pytest.approx(ref.tape_mm)
    assert rr.length_mm == pytest.approx(ref.length_mm)
    assert rr.head.width == PROFILE.head_dots
    assert rr.font_size == dr.font_sizes["t"]
    assert rr.qr is None


def test_object_render_typ():
    ro = render_object(_text(), PROFILE)
    assert isinstance(ro, ObjectRender) and ro.image.mode == "1"


# --- Snapshots ---------------------------------------------------------------------

def test_snapshot_alle_objekte(snapshot):
    objs = (
        TextObject(id="text1", x=4, y=0, w=110, h=40, text="pmx10\nSSD-1"),
        QrObject(id="qr1", x=4, y=44, w=44, h=44, data="112233274913", module=2),
        Code128Object(id="code1", x=116, y=0, w=230, h=88, data="ASN01234"),
        DataMatrixObject(id="dm1", x=352, y=14, w=60, h=60, data="SN274913"),
        IconObject(id="icon1", x=418, y=14, w=60, h=60, icon="tabler:server"),
        LineObject(id="line1", x=484, y=0, w=50, h=88, direction="up", thickness=3, arrow_end=True),
        RectObject(id="rect1", x=540, y=0, w=40, h=88, fill="stripes", radius=6),
        ImageObject(id="image1", x=590, y=0, w=46, h=88, png=gradient_png(), dither="floyd"),
    )
    dr = render_document(doc(*objs, length_mode="fixed", length_mm=80), PROFILE)
    assert dr.errors == ()
    snapshot("doc-alle-objekte", dr.landscape)


def test_snapshot_senkrecht(snapshot):
    objs = (
        TextObject(id="t1", x=0, y=0, w=30, h=88, text="SSD", vertical=True),
        TextObject(id="t2", x=36, y=0, w=150, h=88, text="pmx10\nSN 274913"),
        TextObject(id="t3", x=190, y=0, w=40, h=88, text="Nr 1", rotation=270),
    )
    dr = render_document(doc(*objs), PROFILE)
    assert dr.ok
    snapshot("doc-senkrecht", dr.landscape)


def test_snapshot_invertiert_dunkel(snapshot):
    objs = (
        QrObject(id="qr1", x=0, y=0, w=87, h=88, data="S4EWNX0R123456", module=3),
        TextObject(id="text1", x=95, y=0, w=180, h=88, text="pmx10 · SSD-1\nSN 123456"),
    )
    dr = render_document(doc(*objs), PROFILE, tape=DARK)
    assert dr.ok
    snapshot("doc-invertiert-dunkel", dr.landscape)
