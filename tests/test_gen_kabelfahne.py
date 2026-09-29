import math

import pytest
from PIL import Image, ImageChops

from tapesmith.device.profile import load_profile
from tapesmith.document.generators.kabelfahne import (CABLE_TYPES, cable_diameter, generate, side_view)
from tapesmith.document.render import render_document
from tapesmith.render.compose import mm_to_rows
from tapesmith.render.text import fit_text

PROFILE = load_profile()
PARAMS = {"zugabe_mm": 3.0, "rand_mm": 2.0, "text_mm": 0.0}


def _expected_half_width(lines):
    natural = fit_text(lines, "sans", PROFILE.content_dots, None, "center").image.width
    return max(natural, mm_to_rows(15, PROFILE))


def test_cat6_haengt_laenge_und_knicklinien():
    values = {"kabel_id": "K-017", "kabeltyp": "Cat6", "verlauf": "haengt"}
    out = generate(PARAMS, values, PROFILE)
    half = _expected_half_width(["K-017"])
    rand = mm_to_rows(2.0, PROFILE)
    wrap = mm_to_rows(math.pi * 6.2 + 3.0, PROFILE)
    expected_length = 2 * rand + 2 * half + wrap
    assert mm_to_rows(out.document.length_mm, PROFILE) == expected_length

    fold1 = next(o for o in out.document.objects if o.id == "fold1")
    fold2 = next(o for o in out.document.objects if o.id == "fold2")
    x1, x2 = out.extra["fold_rows"]
    assert fold1.x == x1
    assert fold2.x == x2 - 1

    text_b = next(o for o in out.document.objects if o.id == "text_b")
    assert text_b.rotation == 180

    out_steht_ab = generate(PARAMS, {**values, "verlauf": "steht_ab"}, PROFILE)
    text_b2 = next(o for o in out_steht_ab.document.objects if o.id == "text_b")
    assert text_b2.rotation == 0


def test_durchmesser_hat_vorrang_und_fehlerfaelle():
    values = {"kabel_id": "K-1", "kabeltyp": "Cat6", "durchmesser_mm": "7,5"}
    assert cable_diameter(values) == pytest.approx(7.5)

    with pytest.raises(ValueError, match="unbekannt"):
        cable_diameter({"kabeltyp": "unbekannt"})

    with pytest.raises(ValueError, match="kabel_id"):
        generate(PARAMS, {"kabeltyp": "Cat6"}, PROFILE)


def test_rendern_und_haelfte_b_ist_180_grad_von_a(pixel_colors):
    values = {"kabel_id": "K-017", "quelle": "SW1/P12", "ziel": "pmx10/eno1", "kabeltyp": "Cat6"}
    out = generate(PARAMS, values, PROFILE)
    dr = render_document(out.document, PROFILE)
    assert dr.ok

    a_box = dr.boxes["text_a"]
    b_box = dr.boxes["text_b"]
    a_img = dr.landscape.crop(a_box)
    b_img = dr.landscape.crop(b_box)
    assert a_img.size == b_img.size
    rotated_a = a_img.transpose(Image.Transpose.ROTATE_180)
    diff = ImageChops.difference(rotated_a.convert("L"), b_img.convert("L")).getbbox()
    assert diff is None


def test_side_view_liefert_unterschiedliche_bilder_je_ausrichtung():
    values = {"kabel_id": "K-017", "kabeltyp": "Cat6"}
    haengt = generate(PARAMS, {**values, "verlauf": "haengt"}, PROFILE)
    steht_ab = generate(PARAMS, {**values, "verlauf": "steht_ab"}, PROFILE)

    img_haengt = side_view(haengt, PROFILE)
    img_steht_ab = side_view(steht_ab, PROFILE)
    assert img_haengt.mode == "RGB"
    assert img_haengt.height == 120
    assert img_steht_ab.mode == "RGB"
    assert img_steht_ab.height == 120
    diff = ImageChops.difference(img_haengt.convert("L"), img_steht_ab.convert("L")).getbbox()
    assert diff is not None


def test_snapshot_haengt(snapshot):
    values = {"kabel_id": "K-017", "quelle": "SW1/P12", "ziel": "pmx10/eno1", "kabeltyp": "Cat6",
              "verlauf": "haengt"}
    out = generate(PARAMS, values, PROFILE)
    dr = render_document(out.document, PROFILE)
    assert dr.ok
    snapshot("gen-kabelfahne-haengt", dr.landscape)


def test_snapshot_steht_ab(snapshot):
    values = {"kabel_id": "K-017", "quelle": "SW1/P12", "ziel": "pmx10/eno1", "kabeltyp": "Cat6",
              "verlauf": "steht_ab"}
    out = generate(PARAMS, values, PROFILE)
    dr = render_document(out.document, PROFILE)
    assert dr.ok
    snapshot("gen-kabelfahne-steht-ab", dr.landscape)


def test_duennes_kabel_warnt():
    out = generate(PARAMS, {"kabel_id": "K-1", "kabeltyp": "LWL"}, PROFILE)
    assert any("dünnes Kabel" in w for w in out.warnings)


def test_alle_kabeltypen_bekannt():
    assert set(CABLE_TYPES) == {"Cat6", "Cat6a", "Kaltgeräte", "DAC", "LWL"}
