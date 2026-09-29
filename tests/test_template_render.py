"""`templates/render.py`: der eine Einstieg zum Rendern jeder Vorlage."""

import sys
import types

import pytest

from tapesmith.device.profile import load_profile
from tapesmith.document.generators import GENERATORS, GeneratorOutput
from tapesmith.document.model import LabelDocument
from tapesmith.render.compose import render_label
from tapesmith.tape.profiles import find_tape
from tapesmith.templates.fill import build_spec
from tapesmith.templates.model import template_from_dict
from tapesmith.templates.render import render_meta, render_template

PROFILE = load_profile()


def _document(**extra) -> dict:
    data = {
        "schema_version": 2, "name": "t-doc", "description": "",
        "fields": [
            {"id": "host", "label": "Host", "type": "input", "default": "pmx10"},
            {"id": "sn", "label": "SN", "type": "input", "default": "S4EWNX0R123456"},
        ],
        "document": {
            "objects": [
                {"kind": "text", "id": "t1", "x": 0, "y": 0, "w": 200, "h": 40, "text": "{host}"},
                {"kind": "qr", "id": "q1", "x": 210, "y": 0, "w": 88, "h": 88, "data": "{sn}", "error": "l"},
            ],
        },
    }
    data.update(extra)
    return template_from_dict(data)


# 1. Kurzform: byte-identisch zu render_label(build_spec(...)) ------------------------------

def test_layout_template_bytes_identical_to_render_label():
    template = template_from_dict({
        "schema_version": 2, "name": "datentraeger-mini", "description": "",
        "fields": [
            {"id": "host", "label": "Host", "type": "input", "default": "pmx10"},
            {"id": "slot", "label": "Slot", "type": "input", "default": "SSD-1"},
        ],
        "layout": {"lines": ["{host} · {slot}"]},
    })
    values = {"host": "pmx10", "slot": "SSD-3"}
    tr = render_template(template, values, PROFILE)
    expected = render_label(build_spec(template, values), PROFILE)
    assert tr.result.landscape.tobytes() == expected.landscape.tobytes()
    assert tr.result.head.tobytes() == expected.head.tobytes()
    assert tr.document is None
    assert tr.spec is not None
    assert tr.values == values
    assert tr.shortened == ()
    assert tr.generator is None

    from tapesmith.labelmeta import template_meta
    meta = render_meta(tr)
    expected_meta = template_meta(template, values, build_spec(template, values))
    assert meta.title == expected_meta.title
    assert meta.values == expected_meta.values
    assert meta.spec == expected_meta.spec


# 2. Dokument-Vorlage --------------------------------------------------------------------

def test_document_template_fills_placeholders():
    template = _document()
    values = {"host": "pmx10.home.lan", "sn": "S4EWNX0R123456"}
    tr = render_template(template, values, PROFILE)
    assert tr.document is not None
    assert tr.spec is None
    texts = [o.text for o in tr.document.objects if o.kind == "text"]
    assert texts == ["pmx10.home.lan"]
    meta = render_meta(tr)
    assert meta.spec is None
    assert "pmx10.home.lan" in meta.title


# 3. Generator-Vorlage (Fake-Generator) ----------------------------------------------------

@pytest.fixture
def fake_generator_module(monkeypatch):
    calls = []

    def generate(params, values, profile):
        calls.append((dict(params), dict(values), profile))
        from tapesmith.document.model import TextObject
        doc = LabelDocument(objects=(TextObject(id="t1", x=0, y=0, w=100, h=40, text=values["host"]),))
        return GeneratorOutput(document=doc, notes=("Hinweis: Testgenerator",),
                               warnings=("Warnung: Testgenerator",), extra={"foo": "bar"})

    module = types.ModuleType("tests_fake_gen_render")
    module.PARAMS = {}
    module.generate = generate
    monkeypatch.setitem(sys.modules, "tests_fake_gen_render", module)
    monkeypatch.setitem(GENERATORS, "fake_render", "tests_fake_gen_render")
    return module, calls


def test_generator_template_passes_through_notes_and_warnings(fake_generator_module):
    module, calls = fake_generator_module
    template = template_from_dict({
        "schema_version": 2, "name": "t-gen", "description": "",
        "fields": [{"id": "host", "label": "Host", "type": "input", "default": "pmx10"}],
        "generator": {"name": "fake_render", "params": {}},
    })
    tr = render_template(template, {"host": "pmx10"}, PROFILE)
    assert calls[0][1] == {"host": "pmx10"}
    assert "Hinweis: Testgenerator" in tr.notes
    assert "Warnung: Testgenerator" in tr.warnings
    assert tr.generator is not None
    assert tr.generator.extra == {"foo": "bar"}


# 4. Zielobjekt mit Kürzungsregeln -------------------------------------------------------

def test_target_with_shorten_rules_shortens_until_it_fits():
    template = template_from_dict({
        "schema_version": 2, "name": "t-m2", "description": "",
        "fields": [
            {"id": "host", "label": "Host", "type": "input", "default": ""},
            {"id": "sn", "label": "SN", "type": "input", "default": ""},
        ],
        "layout": {"lines": ["{host}", "{sn}"]},
        "target": "m2-2280",
        "shorten": [
            {"field": "host", "rule": "strip_domain"},
            {"field": "sn", "rule": "last", "n": 6},
        ],
    })
    values = {"host": "pmx10.home.lan", "sn": "S4EWNX0R123456"}
    tr = render_template(template, values, PROFILE)
    assert tr.result.length_mm <= 20 + 1e-6
    assert any(s.startswith("Host") for s in tr.shortened)
    assert tr.values["host"] == "pmx10"
    assert any(n.startswith("Ziel:") for n in tr.notes)


def test_target_without_shortening_needed_leaves_shortened_empty():
    template = template_from_dict({
        "schema_version": 2, "name": "t-m2-short", "description": "",
        "fields": [{"id": "host", "label": "Host", "type": "input", "default": ""}],
        "layout": {"lines": ["{host}"]},
        "target": "m2-2280",
        "shorten": [{"field": "host", "rule": "strip_domain"}],
    })
    tr = render_template(template, {"host": "x"}, PROFILE)
    assert tr.shortened == ()
    assert tr.values["host"] == "x"


# 5. Ziel mit fester Länge -------------------------------------------------------------------

def test_fixed_length_target():
    template = template_from_dict({
        "schema_version": 2, "name": "t-ordner", "description": "",
        "fields": [{"id": "host", "label": "Host", "type": "input", "default": "pmx10"}],
        "layout": {"lines": ["{host}"]},
        "target": "ordner-schmal",
    })
    tr = render_template(template, {"host": "pmx10"}, PROFILE)
    assert abs(tr.result.length_mm - 190) < 1e-6


# 6. Nichts passt -> ValueError des letzten Kandidaten ---------------------------------------

def test_no_candidate_fits_raises_last_value_error():
    template = template_from_dict({
        "schema_version": 2, "name": "t-toolong", "description": "",
        "fields": [{"id": "host", "label": "Host", "type": "input", "default": ""}],
        "layout": {"lines": ["{host}"], "fixed_length_mm": 1},
        "shorten": [{"field": "host", "rule": "last", "n": 3}],
    })
    with pytest.raises(ValueError):
        render_template(template, {"host": "x" * 60}, PROFILE)


# 7. Mindestschrift ----------------------------------------------------------------------

def test_min_font_mm_warns_when_too_small():
    template = template_from_dict({
        "schema_version": 2, "name": "t-minfont", "description": "",
        "fields": [{"id": "host", "label": "Host", "type": "input", "default": "x" * 40}],
        "layout": {"lines": ["{host}"], "fixed_length_mm": 30},
        "checks": {"min_font_mm": 5},
    })
    tr = render_template(template, {"host": "x" * 40}, PROFILE)
    assert any("unter 5" in w for w in tr.warnings)


# 8. Band-Eignung -----------------------------------------------------------------------

def test_tape_reason_set_for_unsuitable_tape_and_none_for_suitable():
    template = template_from_dict({
        "schema_version": 2, "name": "t-tapes", "description": "",
        "fields": [{"id": "host", "label": "Host", "type": "input", "default": "pmx10"}],
        "layout": {"lines": ["{host}"]},
        "tapes": ["material:kunststoff"],
    })
    paper = find_tape("schwarz-weiss-papier")
    plastic = find_tape("schwarz-weiss")
    tr_paper = render_template(template, {"host": "pmx10"}, PROFILE, tape=paper)
    assert tr_paper.tape_reason is not None
    tr_plastic = render_template(template, {"host": "pmx10"}, PROFILE, tape=plastic)
    assert tr_plastic.tape_reason is None


# 9. Kopfbild mit dunklem Band unterscheidet sich ----------------------------------------

def test_n20_qr_head_differs_with_dark_tape():
    template = template_from_dict({
        "schema_version": 2, "name": "t-qr-tape", "description": "",
        "fields": [
            {"id": "host", "label": "Host", "type": "input", "default": "pmx10"},
            {"id": "sn", "label": "SN", "type": "input", "default": "S4EWNX0R123456"},
        ],
        "layout": {"lines": ["{host}"], "qr": "{sn}"},
    })
    values = {"host": "pmx10", "sn": "S4EWNX0R123456"}
    tr_light = render_template(template, values, PROFILE, tape=find_tape("schwarz-weiss"))
    tr_dark = render_template(template, values, PROFILE, tape=find_tape("weiss-schwarz"))
    assert tr_light.result.head.tobytes() != tr_dark.result.head.tobytes()
