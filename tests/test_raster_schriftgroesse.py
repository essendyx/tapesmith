"""Raster-Vorlagen: einheitliche Schriftgröße, Innenabstand, Modi "auto-feld" und feste Größe."""

import pytest

from tapesmith.device.profile import load_profile
from tapesmith.document.generators.raster import PARAMS, generate
from tapesmith.document.render import render_document
from tapesmith.render.compose import mm_to_rows
from tapesmith.render.text import fit_size, ink_extent

PROFILE = load_profile()
PATCH = {"belegung": "server01\nserver02\nNAS\n\nAP-OG"}
SWITCH = PARAMS | {"raster_mm": 14.5}
PAD = mm_to_rows(PARAMS["innenabstand_mm"], PROFILE)
PAD_Q = round(PARAMS["innenabstand_mm"] * PROFILE.dots_per_mm)


def _texts(out):
    return [o for o in out.document.objects if o.kind == "text"]


def _cells(out):
    """(links, rechts) je Feld: erste und letzte Spalte, die nicht zum Trennstrich gehört."""
    seps = sorted(o.x for o in out.document.objects if o.kind == "line")
    return [(a + 2, b - 1) for a, b in zip(seps, seps[1:])]


def test_innenabstand_standard_mindestens_1_mm():
    assert PARAMS["innenabstand_mm"] >= 1.0


def test_einheitliche_groesse_ist_minimum_der_einzelpassungen():
    out = generate(PARAMS, PATCH, PROFILE)
    texts = _texts(out)
    sizes = {t.size for t in texts}
    assert len(sizes) == 1 and None not in sizes
    size = sizes.pop()
    box_h = PROFILE.content_dots - 2 * PAD_Q
    fits = [fit_size([t.text], t.font, box_h, t.w) for t in texts]
    assert size == min(fits)
    assert out.warnings == ()


def test_gemeinsame_grundlinie_und_waagrecht_zentriert():
    out = generate(PARAMS, PATCH, PROFILE)
    texts = _texts(out)
    baselines = set()
    for t in texts:
        top, _bottom, _w = ink_extent([t.text], t.font, t.size)
        baselines.add(t.y - top)
        assert t.align == "center"
    assert len(baselines) == 1


def test_text_haelt_innenabstand_zu_trennstrichen_und_rand():
    for params, values in ((PARAMS, PATCH), (SWITCH, {"belegung": "SW1\nSW2\nUplink\n\nAP-EG"})):
        for mode in ("auto", "auto-feld", "9"):
            out = generate(params, values | {"schriftgroesse": mode}, PROFILE)
            dr = render_document(out.document, PROFILE)
            assert dr.ok, dr.issues
            land = dr.landscape
            for left, right in _cells(out):
                cell = land.crop((left, 0, right + 1, land.height)).convert("L").point(lambda v: 255 - v)
                box = cell.getbbox()
                if box is None:
                    continue
                assert box[0] >= PAD, (mode, left, box)
                assert (right - left + 1) - box[2] >= PAD, (mode, left, box)
                assert box[1] >= PAD_Q and land.height - box[3] >= PAD_Q, (mode, box)


def test_auto_feld_ist_einzeln_eingepasst():
    out = generate(PARAMS, PATCH | {"schriftgroesse": "auto-feld"}, PROFILE)
    texts = _texts(out)
    assert all(t.size is None for t in texts)
    dr = render_document(out.document, PROFILE)
    assert len(set(dr.font_sizes.values())) > 1


def test_feste_groesse_in_mm():
    out = generate(PARAMS, PATCH | {"schriftgroesse": "3"}, PROFILE)
    assert {t.size for t in _texts(out)} == {3 * PROFILE.dots_per_mm}
    assert out.warnings == ()
    out2 = generate(PARAMS, PATCH | {"schriftgroesse": "2,5 mm"}, PROFILE)
    assert {t.size for t in _texts(out2)} == {20}


def test_feste_groesse_zu_gross_wird_verkleinert_mit_warnung():
    out = generate(PARAMS, {"belegung": "A\nKabelbinder"} | {"schriftgroesse": "9"}, PROFILE)
    by_text = {t.text: t.size for t in _texts(out)}
    assert by_text["A"] == 72
    assert by_text["Kabelbinder"] < 72
    assert len(out.warnings) == 1
    assert "Kabelbinder" in out.warnings[0] and "verkleinert" in out.warnings[0]
    dr = render_document(out.document, PROFILE)
    assert dr.ok


def test_ungueltige_schriftgroesse():
    with pytest.raises(ValueError, match="Schriftgröße"):
        generate(PARAMS, PATCH | {"schriftgroesse": "riesig"}, PROFILE)
    with pytest.raises(ValueError, match="außerhalb"):
        generate(PARAMS, PATCH | {"schriftgroesse": "30"}, PROFILE)
