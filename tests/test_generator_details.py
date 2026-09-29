"""Generator-Details: Raster-Trennlinie, Kabelwickel-Beispielwerte.

Die Editor-Tests zur Band-Eignung (Qt) sind mit dem Qt-Editor entfallen; die Band-Rückfrage prüfen
jetzt die Web-API-Tests (`tape_reason` in `test_webapi_labels_print.py`)."""

import pytest

from tapesmith.device.profile import load_profile
from tapesmith.document.generators.kabelwickel import generate as gen_kabelwickel
from tapesmith.document.generators.kabelwickel import PARAMS as KABELWICKEL_PARAMS
from tapesmith.document.generators.raster import PARAMS as RASTER_PARAMS
from tapesmith.document.generators.raster import generate as gen_raster
from tapesmith.document.render import render_document
from tapesmith.templates.lint import lint_template
from tapesmith.templates.store import find_template

PROFILE = load_profile()


# 7 ------------------------------------------------------------------- Raster

@pytest.mark.parametrize("name", ["raster-patchpanel", "raster-sicherungskasten",
                                  "raster-sortiment", "raster-switch"])
def test_raster_vorlagen_ragen_nicht_ueber_den_rand(name):
    template = find_template(name)
    issues = lint_template(template, PROFILE)
    assert not any("ragt über den Labelrand" in i.message for i in issues)


def test_raster_generator_linien_innerhalb_der_laenge():
    from tapesmith.render.compose import mm_to_rows

    values = {"belegung": "\n".join(f"P{i}" for i in range(1, 25))}
    out = gen_raster(RASTER_PARAMS, values, PROFILE)
    dr = render_document(out.document, PROFILE)
    assert not any("ragt über den Labelrand" in w.message for w in dr.issues)
    doc_length_rows = mm_to_rows(out.document.length_mm, PROFILE)
    line_objects = [o for o in out.document.objects if o.kind == "line"]
    assert line_objects
    for obj in line_objects:
        assert obj.x + obj.w <= doc_length_rows


# 8 --------------------------------------------------------------- Kabelwickel

def test_kabelwickel_beispielwerte_ohne_befunde():
    template = find_template("kabelwickel")
    issues = lint_template(template, PROFILE)
    beispiel_issues = [i for i in issues if i.data == "Beispiel"]
    assert beispiel_issues == []


def test_kabelwickel_generate_zwei_wiederholungen():
    out = gen_kabelwickel(KABELWICKEL_PARAMS, {"kabel_id": "K-017", "kabeltyp": "Cat6"}, PROFILE)
    assert out.extra["repeats"] >= 2


def test_kabelwickel_lange_id_auf_dac_nur_einmal_kein_ueberstand():
    out = gen_kabelwickel(KABELWICKEL_PARAMS,
                          {"kabel_id": "SEHR-LANGE-KABEL-ID-0001", "kabeltyp": "DAC"}, PROFILE)
    assert out.extra["repeats"] == 1
    dr = render_document(out.document, PROFILE)
    assert not any("ragt" in i.message for i in dr.issues)


def test_kabelwickel_maximaldaten_nur_zu_wenig_wiederholungen():
    template = find_template("kabelwickel")
    issues = lint_template(template, PROFILE)
    maximal_issues = [i for i in issues if i.data == "Maximal"]
    assert all("passt nur einmal" in i.message for i in maximal_issues)
    assert not any("ragt über den Labelrand" in i.message for i in maximal_issues)
