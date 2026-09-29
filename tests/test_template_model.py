import json

import pytest

from tapesmith.templates import model
from tapesmith.templates.model import SCHEMA_VERSION, TemplateError, load_template, template_from_dict, template_to_dict

BASE = {
    "schema_version": 2,
    "name": "test",
    "description": "Test",
    "fields": [
        {"id": "host", "label": "Host", "type": "input", "default": "pmx10"},
        {"id": "sn", "label": "SN", "type": "input", "clean": "serial", "required": True},
        {"id": "datum", "label": "Datum", "type": "date", "format": "%d.%m.%Y"},
    ],
    "layout": {"lines": ["{host}", "SN {sn|last:6}", "{sn_model} {datum}"], "font": "sans"},
}


def write(tmp_path, data, name="t.tapesmith.json"):
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_valid_template_roundtrip(tmp_path):
    t = load_template(write(tmp_path, BASE))
    assert t.name == "test" and t.schema_version == SCHEMA_VERSION
    assert t.field("sn").required and t.field("sn").clean == "serial"
    assert template_to_dict(t) == BASE


@pytest.mark.parametrize("mutate, message", [
    (lambda d: d.pop("schema_version"), "schema_version"),
    (lambda d: d.update(schema_version=99), "neuer"),
    (lambda d: d.update(schema_version=True), "schema_version"),
    (lambda d: d.update(min_app_version="99.0.0"), "App-Version"),
    (lambda d: d["fields"].append({"id": "host", "label": "X", "type": "input"}), "doppelt"),
    (lambda d: d["fields"].append({"id": "x", "label": "X", "type": "formel"}), "Typ"),
    (lambda d: d["fields"].append({"id": "Bad-Id", "label": "X", "type": "input"}), "Feld-ID"),
    (lambda d: d["fields"].append({"id": "x", "label": "X", "type": "input", "clean": "iban"}), "clean"),
    (lambda d: d["fields"].append({"id": "x", "label": "X", "type": "date", "clean": "serial"}), "clean"),
    (lambda d: d["fields"].append({"id": "x", "label": "X", "type": "date", "format": "%Q"}), "format"),
    (lambda d: d["fields"].append({"id": "x", "label": "X", "type": "counter", "format": "{:z}"}), "format"),
    (lambda d: d["fields"].append({"id": "x", "label": "X", "type": "date", "offset_days": "bald"}), "offset_days"),
    (lambda d: d["layout"].update(farbe="rot"), "Layout"),
    (lambda d: d["layout"].update(lines=["{unbekannt}"]), "unbekannt"),
    (lambda d: d["layout"].update(lines=[]), "lines"),
    (lambda d: d["layout"].update(lines=["a", "b", "c", "d"]), "lines"),
    (lambda d: d["layout"].update(lines=[1]), "lines"),
    (lambda d: d["layout"].update(font="comic"), "font"),
    (lambda d: d["layout"].update(align="justify"), "align"),
    (lambda d: d["layout"].update(qr_error="x"), "qr_error"),
    (lambda d: d["layout"].update(font_size=1.5), "font_size"),
    (lambda d: d["layout"].update(font_size=True), "font_size"),
    (lambda d: d["layout"].update(font_size=0), "font_size"),
    (lambda d: d["layout"].update(max_length_mm=True), "max_length_mm"),
    (lambda d: d["layout"].update(max_length_mm=0), "max_length_mm"),
    (lambda d: d["layout"].update(fixed_length_mm=-5), "fixed_length_mm"),
    (lambda d: d["layout"].update(margin_mm=-1), "margin_mm"),
    (lambda d: d["layout"].update(margin_mm=True), "margin_mm"),
    (lambda d: d["layout"].update(qr=123), "qr"),
    (lambda d: d["layout"].update(lines=["{host|last:0}"]), "last:0"),
    (lambda d: d["layout"].update(lines=["{host|first:0}"]), "first:0"),
])
def test_invalid_templates(tmp_path, mutate, message):
    data = json.loads(json.dumps(BASE))
    mutate(data)
    with pytest.raises(TemplateError, match=message):
        load_template(write(tmp_path, data))


def test_margin_mm_zero_is_allowed(tmp_path):
    data = json.loads(json.dumps(BASE))
    data["layout"]["margin_mm"] = 0
    t = load_template(write(tmp_path, data))
    assert t.layout["margin_mm"] == 0


def test_field_keys_derived_from_dataclass():
    # alt_map (Tabellen der anderen Sprachen) wird nie gespeichert und ist kein Schlüssel der Datei.
    assert set(model._FIELD_KEYS) == {f.name for f in __import__("dataclasses").fields(model.Field)} - {"alt_map"}


def test_filter_last_and_first_zero_rejected():
    with pytest.raises(TemplateError, match="last:0"):
        model.apply_filter("X", "last:0")
    with pytest.raises(TemplateError, match="first:0"):
        model.apply_filter("X", "first:0")


def test_broken_json_is_template_error(tmp_path):
    path = tmp_path / "kaputt.tapesmith.json"
    path.write_text("{nicht json", encoding="utf-8")
    with pytest.raises(TemplateError, match="kaputt"):
        load_template(path)


def test_migration_with_backup(tmp_path, monkeypatch):
    v1 = {**BASE, "schema_version": 1}
    monkeypatch.setattr(model, "SCHEMA_VERSION", 3)
    monkeypatch.setattr(model, "MIGRATIONS", {
        1: lambda d: {**d, "description": d["description"] + " (v2)"},
        2: lambda d: d,
    })
    path = write(tmp_path, v1)
    t = load_template(path)
    assert t.schema_version == 3 and t.description == "Test (v2)"
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == 3
    backup = tmp_path / "t.tapesmith.json.bak-v1"
    assert json.loads(backup.read_text(encoding="utf-8")) == v1


def test_missing_migration_step(tmp_path, monkeypatch):
    v1 = {**BASE, "schema_version": 1}
    monkeypatch.setattr(model, "SCHEMA_VERSION", 2)
    monkeypatch.setattr(model, "MIGRATIONS", {})
    with pytest.raises(TemplateError, match="Migration"):
        load_template(write(tmp_path, v1))


def test_from_dict_without_path():
    t = template_from_dict(BASE)
    assert t.path is None and [f.id for f in t.fields] == ["host", "sn", "datum"]
