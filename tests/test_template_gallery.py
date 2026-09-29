"""Tests für die Vorlagengalerie-Kernfunktionen (ohne Qt)."""

import json
import zipfile
from datetime import datetime

import pytest
from PIL import Image

from tapesmith.history import HistoryStore
from tapesmith.jobs import JobMeta
from tapesmith.templates.gallery import (
    OVERLAP_COLOR,
    WRAP_COLOR,
    export_package,
    favorites,
    group_by_category,
    import_package,
    recent_template_names,
    sample_values,
    search_templates,
    toggle_favorite,
    wrap_marks_image,
)
from tapesmith.templates.model import template_from_dict

DATENTRAEGER = {
    "schema_version": 2, "name": "datentraeger", "description": "SN/by-id",
    "category": "Datenträger", "tags": ["ssd"],
    "fields": [
        {"id": "host", "label": "Host", "type": "input", "default": "pmx10"},
        {"id": "sn", "label": "Seriennummer", "type": "input", "required": True},
    ],
    "layout": {"lines": ["{host}", "{sn}"]},
    "sample": {"host": "pmx10", "sn": "12345"},
}

KABEL = {
    "schema_version": 2, "name": "kabelfahne", "description": "Kabeltyp",
    "category": "Kabel", "tags": ["kabel"],
    "fields": [{"id": "kabel_id", "label": "Kabel-ID", "type": "input", "required": True}],
    "layout": {"lines": ["{kabel_id}"]},
}

OHNE_KATEGORIE = {
    "schema_version": 2, "name": "frei", "description": "",
    "fields": [{"id": "t", "label": "Text", "type": "input"}],
    "layout": {"lines": ["{t}"]},
}


@pytest.fixture
def templates():
    return [template_from_dict(DATENTRAEGER), template_from_dict(KABEL), template_from_dict(OHNE_KATEGORIE)]


def test_search_findet_ueber_feldlabel_und_tag_zwei_woerter(templates):
    assert [t.name for t in search_templates(templates, "seriennummer")] == ["datentraeger"]
    assert [t.name for t in search_templates(templates, "kabel")] == ["kabelfahne"]
    # zwei Wörter müssen beide treffen
    assert [t.name for t in search_templates(templates, "datentraeger seriennummer")] == ["datentraeger"]
    assert search_templates(templates, "datentraeger nirgendwo") == []
    assert search_templates(templates, "") == templates


def test_group_by_category_inkl_allgemein(templates):
    groups = group_by_category(templates)
    assert groups["Allgemein"] == [templates[2]]
    assert groups["Datenträger"] == [templates[0]]
    assert groups["Kabel"] == [templates[1]]
    assert list(groups) == sorted(groups)


def test_recent_template_names_neueste_zuerst_und_nur_ok(tmp_path):
    history = HistoryStore(tmp_path / "h.db")
    meta_a = JobMeta(source="gui", kind="template", title="a", template="a-vorlage", values={})
    meta_b = JobMeta(source="gui", kind="template", title="b", template="b-vorlage", values={})
    meta_err = JobMeta(source="gui", kind="template", title="e", template="fehler-vorlage", values={})
    history.record(meta_a, landscape=None, head=None, length_mm=10, tape_mm=20, status="ok")
    history.record(meta_err, landscape=None, head=None, length_mm=10, tape_mm=20, status="fehler")
    history.record(meta_b, landscape=None, head=None, length_mm=10, tape_mm=20, status="ok")

    names = recent_template_names(history, n=8, scan_limit=300)
    assert names == ["b-vorlage", "a-vorlage"]


def test_toggle_favorite_an_und_aus_mit_fake_save():
    cfg = {"gui": {"favorites": []}}
    saved = []

    def fake_save(updates):
        saved.append(updates)
        return updates

    result = toggle_favorite(cfg, "datentraeger", fake_save)
    assert result == ["datentraeger"]
    assert favorites(cfg) == ["datentraeger"]
    assert saved[-1]["gui"]["favorites"] == ["datentraeger"]

    result = toggle_favorite(cfg, "datentraeger", fake_save)
    assert result == []
    assert favorites(cfg) == []


def test_sample_values_default_ueberschrieben_von_sample():
    t = template_from_dict(DATENTRAEGER)
    assert sample_values(t) == {"host": "pmx10", "sn": "12345"}


def test_export_import_package_roundtrip(tmp_path):
    templates_list = [template_from_dict(DATENTRAEGER), template_from_dict(KABEL)]
    zip_path = tmp_path / "paket.zip"
    export_package(templates_list, zip_path)

    target = tmp_path / "import1"
    names = import_package(zip_path, target)
    assert set(names) == {"datentraeger", "kabelfahne"}
    for name in names:
        data = json.loads((target / f"{name}.tapesmith.json").read_text(encoding="utf-8"))
        template_from_dict(data)  # lädt fehlerfrei


def test_import_package_namenskonflikt_bekommt_zusatz(tmp_path):
    templates_list = [template_from_dict(DATENTRAEGER)]
    zip_path = tmp_path / "paket.zip"
    export_package(templates_list, zip_path)

    target = tmp_path / "import2"
    import_package(zip_path, target)
    names = import_package(zip_path, target)
    assert names == ["datentraeger-2"]
    data = json.loads((target / "datentraeger-2.tapesmith.json").read_text(encoding="utf-8"))
    assert data["name"] == "datentraeger-2"


def test_import_package_pfad_traversal_wirft_und_schreibt_nichts(tmp_path):
    zip_path = tmp_path / "boese.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"format": "tapesmith-paket", "version": 1,
                                                  "templates": ["x"]}))
        zf.writestr("../boese.json", "{}")

    target = tmp_path / "import3"
    with pytest.raises(ValueError):
        import_package(zip_path, target)
    assert not target.exists()


def test_import_package_ungueltige_vorlage_wirft_und_schreibt_nichts(tmp_path):
    zip_path = tmp_path / "ungueltig.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"format": "tapesmith-paket", "version": 1,
                                                  "templates": ["kaputt"]}))
        zf.writestr("kaputt.tapesmith.json", json.dumps({"schema_version": 2, "name": "kaputt",
                                                        "fields": [], "layout": {"font": "unbekannt"}}))

    target = tmp_path / "import4"
    with pytest.raises(ValueError):
        import_package(zip_path, target)
    assert not target.exists()


def test_wrap_marks_image_groesse_und_farben():
    landscape = Image.new("1", (200, 88), 255)
    image = wrap_marks_image(landscape, {"wrap_rows": 120, "overlap_rows": 80})
    assert image.size == (200, 98)
    assert image.getpixel((10, 93)) == WRAP_COLOR
    assert image.getpixel((150, 93)) == OVERLAP_COLOR
    assert image.getpixel((120, 40)) == OVERLAP_COLOR


def test_wrap_marks_image_overlap_ueber_breite_geklemmt():
    landscape = Image.new("1", (100, 50), 255)
    image = wrap_marks_image(landscape, {"wrap_rows": 90, "overlap_rows": 500})
    assert image.size == (100, 60)
    assert image.getpixel((95, 55)) == OVERLAP_COLOR
