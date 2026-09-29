import json

import pytest

from tapesmith import paths
from tapesmith.templates.model import (
    Field,
    ShortenRule,
    Template,
    TemplateError,
    load_template,
    template_from_dict,
    template_to_dict,
)
from tapesmith.document.generators import GeneratorRef
from tapesmith.document.model import LabelDocument, TextObject, QrObject
from tapesmith.templates.store import builtin_templates, list_templates, user_dir

V1_LAYOUT_TEMPLATE = {
    "schema_version": 1,
    "name": "alt",
    "description": "Alte Vorlage",
    "fields": [{"id": "host", "label": "Host", "type": "input", "default": "pmx10"}],
    "layout": {"lines": ["{host}"], "font": "sans"},
}


def write(tmp_path, data, name="t.tapesmith.json"):
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


# 1. Migration v1 -> v2 mit Backup ----------------------------------------------------------

def test_v1_file_migrates_to_v2_with_backup(tmp_path):
    path = write(tmp_path, V1_LAYOUT_TEMPLATE)
    t = load_template(path)
    assert t.schema_version == 2
    assert t.kind == "layout"
    assert t.layout == {"lines": ["{host}"], "font": "sans"}
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["schema_version"] == 2
    assert on_disk["layout"] == {"lines": ["{host}"], "font": "sans"}
    backup = tmp_path / "t.tapesmith.json.bak-v1"
    assert json.loads(backup.read_text(encoding="utf-8")) == V1_LAYOUT_TEMPLATE


# 2. Dokument-Vorlage ------------------------------------------------------------------------

def _document_data():
    return {
        "version": 1,
        "objects": [
            {"kind": "text", "id": "t1", "x": 0, "y": 0, "w": 200, "h": 40, "text": "{host}"},
            {"kind": "qr", "id": "q1", "x": 0, "y": 45, "w": 60, "h": 60, "data": "{sn}"},
        ],
    }


def _document_base():
    return {
        "schema_version": 2, "name": "doc", "description": "",
        "fields": [
            {"id": "host", "label": "Host", "type": "input"},
            {"id": "sn", "label": "SN", "type": "input"},
        ],
        "document": _document_data(),
    }


def test_document_template_loads_with_kind_document(tmp_path):
    t = load_template(write(tmp_path, _document_base()))
    assert t.kind == "document"
    assert isinstance(t.document, LabelDocument)
    assert len(t.document.objects) == 2


def test_document_unknown_placeholder_rejected(tmp_path):
    data = _document_base()
    data["document"]["objects"][0]["text"] = "{gibtsnicht}"
    with pytest.raises(TemplateError, match="unbekannt"):
        load_template(write(tmp_path, data))


def test_document_and_layout_together_rejected(tmp_path):
    data = _document_base()
    data["layout"] = {"lines": ["{host}"]}
    with pytest.raises(TemplateError, match="schließen sich aus"):
        load_template(write(tmp_path, data))


def test_missing_representation_rejected(tmp_path):
    data = _document_base()
    del data["document"]
    with pytest.raises(TemplateError, match="braucht layout, document oder generator"):
        load_template(write(tmp_path, data))


# 3. Generator-Vorlage -----------------------------------------------------------------------

def test_generator_template_loads_without_importing_module(tmp_path):
    data = {
        "schema_version": 2, "name": "gen", "description": "",
        "fields": [{"id": "laenge_m", "label": "Länge (m)", "type": "input"}],
        "generator": {"name": "kabelfahne", "params": {}},
    }
    t = load_template(write(tmp_path, data))
    assert t.kind == "generator"
    assert t.generator == GeneratorRef(name="kabelfahne", params={})


def test_generator_unknown_name_rejected(tmp_path):
    data = {
        "schema_version": 2, "name": "gen", "description": "", "fields": [],
        "generator": {"name": "xyz", "params": {}},
    }
    with pytest.raises(TemplateError, match="xyz"):
        load_template(write(tmp_path, data))


# 4. Neue Schlüssel ---------------------------------------------------------------------------

BASE_V2 = {
    "schema_version": 2, "name": "t", "description": "",
    "fields": [{"id": "host", "label": "Host", "type": "input", "default": "pmx10"}],
    "layout": {"lines": ["{host}"]},
}


def test_unknown_top_level_key_rejected():
    data = {**BASE_V2, "farbe": "rot"}
    with pytest.raises(TemplateError, match=r"unbekannte Schlüssel"):
        template_from_dict(data)


def test_sample_unknown_field_rejected():
    data = {**BASE_V2, "sample": {"gibtsnicht": "x"}}
    with pytest.raises(TemplateError, match="sample"):
        template_from_dict(data)


def test_target_valid_and_invalid():
    ok = template_from_dict({**BASE_V2, "target": "m2-2280"})
    assert ok.target == "m2-2280"
    with pytest.raises(TemplateError, match="mars"):
        template_from_dict({**BASE_V2, "target": "mars"})


def test_shorten_unknown_rule_rejected():
    data = {**BASE_V2, "shorten": [{"field": "host", "rule": "middle", "n": 3}]}
    with pytest.raises(TemplateError, match="middle"):
        template_from_dict(data)


def test_tapes_unknown_material_rejected():
    data = {**BASE_V2, "tapes": ["material:holz"]}
    with pytest.raises(TemplateError, match="holz"):
        template_from_dict(data)


def test_default_copies_zero_rejected():
    data = {**BASE_V2, "default_copies": 0}
    with pytest.raises(TemplateError, match="default_copies"):
        template_from_dict(data)


def test_checks_unknown_key_rejected():
    data = {**BASE_V2, "checks": {"x": 1}}
    with pytest.raises(TemplateError, match="checks"):
        template_from_dict(data)


# 5. Felder -------------------------------------------------------------------------------

def test_lookup_field_without_existing_source_rejected():
    data = {
        "schema_version": 2, "name": "t", "description": "",
        "fields": [{"id": "x", "label": "X", "type": "lookup", "source": "gibtsnicht", "map": {}}],
        "layout": {"lines": ["{x}"]},
    }
    with pytest.raises(TemplateError, match="source"):
        template_from_dict(data)


def test_date_field_unknown_offset_field_rejected():
    data = {
        "schema_version": 2, "name": "t", "description": "",
        "fields": [{"id": "d", "label": "D", "type": "date", "offset_field": "gibtsnicht"}],
        "layout": {"lines": ["{d}"]},
    }
    with pytest.raises(TemplateError, match="offset_field"):
        template_from_dict(data)


def test_max_len_on_fixed_field_rejected():
    data = {
        "schema_version": 2, "name": "t", "description": "",
        "fields": [{"id": "x", "label": "X", "type": "fixed", "default": "y", "max_len": 5}],
        "layout": {"lines": ["{x}"]},
    }
    with pytest.raises(TemplateError, match="max_len"):
        template_from_dict(data)


# 6. Rundlauf -------------------------------------------------------------------------------

def test_roundtrip_with_all_new_properties():
    data = {
        "schema_version": 2, "name": "gefriergut", "description": "Gefriergut",
        "category": "Haushalt", "tags": ["küche", "tiefkühl"],
        "fields": [
            {"id": "inhalt", "label": "Inhalt", "type": "input", "required": True, "max_len": 20},
            {"id": "kategorie", "label": "Kategorie", "type": "input", "choices": ["Fleisch", "Gemüse"],
             "default": "Fleisch"},
            {"id": "tage", "label": "Haltbar (Tage)", "type": "lookup", "source": "kategorie",
             "map": {"Fleisch": "180", "Gemüse": "365"}},
            {"id": "eingefroren", "label": "Eingefroren", "type": "date"},
            {"id": "bis", "label": "Haltbar bis", "type": "date", "base_field": "eingefroren",
             "offset_field": "tage", "offset_months": 1},
        ],
        "layout": {"lines": ["{inhalt}", "{bis}"]},
        "sample": {"inhalt": "Gulasch", "kategorie": "Fleisch"},
        "target": "geoeffnet",
        "shorten": [{"field": "inhalt", "rule": "first", "n": 12}],
        "tapes": ["material:kunststoff"],
        "default_copies": 2,
        "checks": {"min_font_mm": 2.0},
    }
    t = template_from_dict(data)
    back = template_to_dict(t)
    assert back == data
    assert template_from_dict(back) == dataclasses_replace_path_none(t)


def dataclasses_replace_path_none(t: Template) -> Template:
    import dataclasses
    return dataclasses.replace(t, path=None)


# 7. Mitgelieferte Vorlagen ------------------------------------------------------------------

def test_builtin_templates_are_v2_with_category_and_sample(capsys):
    templates = {t.name: t for t in builtin_templates()}
    assert set(("datentraeger", "datentraeger-qr")) <= set(templates)
    for name in ("datentraeger", "datentraeger-qr"):
        t = templates[name]
        assert t.schema_version == 2
        assert t.category == "Datenträger"
        assert t.sample
    assert capsys.readouterr().err == ""


# 8. Benutzerdefinierter Vorlagenordner --------------------------------------------------

def test_user_dir_uses_configured_templates_dir(tmp_path, monkeypatch):
    target = tmp_path / "labels"
    from tapesmith import config as config_module
    monkeypatch.setattr(config_module, "load_config", lambda: {**config_module.DEFAULTS, "templates_dir": str(target)})
    assert user_dir() == target
    assert target.is_dir()

    data = {**BASE_V2, "name": "eigene"}
    (target / "eigene.tapesmith.json").write_text(json.dumps(data), encoding="utf-8")
    names = [t.name for t in list_templates()]
    assert "eigene" in names
