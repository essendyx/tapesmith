"""Vorlagen: Feld `schriftgroesse` (Schema-Schlüssel `text_height`), Rendern, Lint, Kompatibilität."""

from datetime import datetime

import pytest

from tapesmith.device.profile import load_profile
from tapesmith.render.textsize import AUTO, AUTO_FIELD, TEXT_SIZE_FIELD
from tapesmith.templates import store
from tapesmith.templates.fill import CounterStore, form_fields, resolve_values
from tapesmith.templates.lint import lint_template
from tapesmith.templates.model import TemplateError, template_from_dict, template_to_dict
from tapesmith.templates.render import render_template

PROFILE = load_profile()
NOW = datetime(2026, 9, 29, 12, 0)


def _doc_template(**extra):
    data = {
        "schema_version": 2, "name": "t",
        "fields": [{"id": "a", "label": "A", "type": "input"}],
        "document": {"objects": [
            {"kind": "text", "id": "text1", "x": 0, "y": 0, "w": 300, "h": 88, "text": "{a}", "size": None},
        ]},
    }
    data.update(extra)
    return template_from_dict(data)


def _size_field(t):
    return t.text_size_field


def test_raster_vorlage_hat_feld_mit_auto_feld():
    t = store.find_template("raster-patchpanel")
    f = _size_field(t)
    assert f is not None and f.type == "input" and not f.required
    assert f.label == "Schriftgröße"
    assert f.default == AUTO
    assert f.choices[:2] == (AUTO, AUTO_FIELD)
    assert "2" in f.choices and "9" in f.choices


def test_text_und_layoutvorlagen_ohne_auto_feld():
    for name in ("asset-kurz", "absender"):
        f = _size_field(store.find_template(name))
        assert f is not None, name
        assert AUTO_FIELD not in f.choices
        assert f.default == AUTO


def test_vorlagen_ohne_auto_fit_text_haben_kein_feld():
    assert _size_field(store.find_template("kabelfahne")) is None
    qr_only = template_from_dict({
        "schema_version": 2, "name": "q", "fields": [],
        "document": {"objects": [{"kind": "qr", "id": "qr1", "x": 0, "y": 0, "w": 88, "h": 88, "data": "x"}]},
    })
    assert _size_field(qr_only) is None


def test_implizites_feld_wird_nicht_gespeichert():
    t = store.find_template("raster-patchpanel")
    data = template_to_dict(t)
    assert TEXT_SIZE_FIELD not in [f["id"] for f in data["fields"]]
    assert "text_height" not in data
    again = template_from_dict(data)
    assert _size_field(again) == _size_field(t)
    assert TEXT_SIZE_FIELD not in [f.id for f in t.fields]
    assert t.text_size_implicit
    assert form_fields(t)[-1] == _size_field(t)


def test_schema_text_height_standard_und_abschalten():
    t = _doc_template(text_height=4)
    assert _size_field(t).default == "4"
    assert template_to_dict(t)["text_height"] == "4"
    off = _doc_template(text_height=False)
    assert _size_field(off) is None
    assert template_to_dict(off)["text_height"] is False


@pytest.mark.parametrize("bad", ["riesig", 50, "auto-feld", True])
def test_schema_text_height_ungueltig(bad):
    with pytest.raises(TemplateError, match="text_height"):
        _doc_template(text_height=bad)


def test_schema_text_height_ohne_auto_text_ist_fehler():
    with pytest.raises(TemplateError, match="text_height"):
        template_from_dict({
            "schema_version": 2, "name": "q", "fields": [], "text_height": "5",
            "document": {"objects": [{"kind": "qr", "id": "qr1", "x": 0, "y": 0, "w": 88, "h": 88, "data": "x"}]},
        })


def test_eigenes_feld_schriftgroesse_wird_geprueft():
    ok = _doc_template(fields=[{"id": "a", "label": "A", "type": "input"},
                               {"id": "schriftgroesse", "label": "Größe", "type": "input", "default": "3,5",
                                "choices": ["3", "3,5"]}])
    assert _size_field(ok).label == "Größe"
    assert TEXT_SIZE_FIELD in [f["id"] for f in template_to_dict(ok)["fields"]]
    with pytest.raises(TemplateError, match="schriftgroesse"):
        _doc_template(fields=[{"id": "a", "label": "A", "type": "input"},
                              {"id": "schriftgroesse", "label": "G", "type": "input", "default": "gross"}])


def test_resolve_values_nimmt_schriftgroesse_an(tmp_path):
    t = store.find_template("raster-patchpanel")
    r = resolve_values(t, {"belegung": "a", TEXT_SIZE_FIELD: "5"}, NOW, CounterStore(tmp_path / "c.json"))
    assert r.values[TEXT_SIZE_FIELD] == "5"
    r2 = resolve_values(t, {"belegung": "a"}, NOW, CounterStore(tmp_path / "c.json"))
    assert TEXT_SIZE_FIELD not in r2.values


def test_dokumentvorlage_standard_unveraendert():
    t = store.find_template("asset-kurz")
    values = dict(t.sample)
    plain = render_template(t, values, PROFILE)
    with_auto = render_template(t, values | {TEXT_SIZE_FIELD: "auto"}, PROFILE)
    assert plain.result.landscape.tobytes() == with_auto.result.landscape.tobytes()


def test_dokumentvorlage_feste_groesse_und_verkleinerung():
    t = store.find_template("asset-kurz")
    small = render_template(t, dict(t.sample) | {TEXT_SIZE_FIELD: "3"}, PROFILE)
    sizes = {o.id: o.size for o in small.document.objects if o.kind == "text"}
    assert set(sizes.values()) == {24}
    assert not any("verkleinert" in w for w in small.warnings)
    big = render_template(t, dict(t.sample) | {TEXT_SIZE_FIELD: "9"}, PROFILE)
    assert any("verkleinert" in w for w in big.warnings)
    assert all(o.size < 72 for o in big.document.objects if o.kind == "text")


def test_layoutvorlage_feste_groesse_und_verkleinerung():
    t = store.find_template("absender")
    auto = render_template(t, dict(t.sample), PROFILE)
    small = render_template(t, dict(t.sample) | {TEXT_SIZE_FIELD: "2"}, PROFILE)
    assert small.result.font_size == 16
    assert not any("verkleinert" in w for w in small.warnings)
    big = render_template(t, dict(t.sample) | {TEXT_SIZE_FIELD: "9"}, PROFILE)
    assert big.result.font_size == auto.result.font_size
    assert any("verkleinert" in w for w in big.warnings)


def test_ungueltige_eingabe_ist_vorlagenfehler():
    t = store.find_template("absender")
    with pytest.raises(TemplateError, match="Schriftgröße"):
        render_template(t, dict(t.sample) | {TEXT_SIZE_FIELD: "gross"}, PROFILE)
    t2 = store.find_template("asset-kurz")
    with pytest.raises(TemplateError, match="Raster"):
        render_template(t2, dict(t2.sample) | {TEXT_SIZE_FIELD: "auto-feld"}, PROFILE)


def test_lint_kennt_schriftgroesse():
    t = _doc_template(text_height="9", sample={"a": "Beispieltext"})
    issues = lint_template(t, PROFILE, now=NOW)
    assert any("verkleinert" in i.message for i in issues)
