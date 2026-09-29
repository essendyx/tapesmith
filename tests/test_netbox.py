"""NetBox-CSV-Import (Spaltenzuordnung, Zeilenaufbereitung, Vorlagen-Zeilen)."""

from pathlib import Path

import pytest

from tapesmith.dataimport.mapping import ColumnMapping, MappingStore
from tapesmith.integrations import netbox, tia606

DATA = Path(__file__).parent / "data" / "netbox"


def _table(name: str):
    return netbox.read_export(DATA.joinpath(name).read_bytes(), source=name)


def test_suggest_mapping_english_headers():
    table = _table("cables-export.csv")
    mapping = netbox.suggest_mapping(table)
    assert mapping["kabel_id"] == "Label"
    assert mapping["quelle"] == "Side A"
    assert mapping["ziel"] == "Side B"
    assert mapping["kabeltyp"] == "Type"


def test_suggest_mapping_german_headers():
    table = _table("cables-export-semicolon.csv")
    mapping = netbox.suggest_mapping(table)
    assert mapping["kabel_id"] == "Kabel"
    assert mapping["quelle"] == "Seite A"
    assert mapping["ziel"] == "Seite B"
    assert mapping["kabeltyp"] == "Typ"


def test_suggest_mapping_prefers_stored(tmp_path):
    table = _table("cables-export.csv")
    store = MappingStore(tmp_path / "mappings.json")
    store.save("netbox-kabel", table.headers, ColumnMapping(columns={"kabel_id": "ID"}))
    mapping = netbox.suggest_mapping(table, store)
    assert mapping == {"kabel_id": "ID"}


def test_combine_side():
    assert netbox.combine_side("SW1", "P12") == "SW1/P12"
    assert netbox.combine_side("SW1", "") == "SW1"
    assert netbox.combine_side("", "P12") == "P12"


def test_build_rows_combines_side_and_maps_types(tmp_path):
    table = _table("cables-export.csv")
    register = tia606.KabelRegister(tmp_path / "kabel.json")
    mapping = {"kabel_id": "Label", "quelle": ["Side A", "Termination A"], "ziel": ["Side B", "Termination B"],
              "kabeltyp": "Type"}
    result = netbox.build_rows(table, mapping, register=register)
    first = result.rows[0]
    assert first.quelle == "SW1/P12"
    assert first.ziel == "pmx10/eno1"
    assert first.kabeltyp == "Cat6"
    types = {row.kabel_id: row.kabeltyp for row in result.rows if row.kabel_id}
    assert types["K-102"] == "LWL"
    assert types["K-104"] == "Kaltgeräte"


def test_build_rows_assigns_missing_ids(tmp_path):
    table = _table("cables-export.csv")
    register = tia606.KabelRegister(tmp_path / "kabel.json")
    mapping = {"kabel_id": "Label", "quelle": "Side A", "ziel": "Side B", "kabeltyp": "Type"}

    calls: list[int] = []

    def new_id(n: int) -> list[str]:
        calls.append(n)
        return [f"K-{900 + i}" for i in range(n)]

    result = netbox.build_rows(table, mapping, register=register, new_id=new_id)
    assert calls == [2]
    neu_rows = [row for row in result.rows if row.neu]
    assert {row.kabel_id for row in neu_rows} == {"K-900", "K-901"}
    assert result.warnings == ()


def test_build_rows_without_new_id_warns():
    table = _table("cables-export.csv")

    class DummyRegister:
        def duplicates(self, ids):
            return []

    mapping = {"kabel_id": "Label"}
    result = netbox.build_rows(table, mapping, register=DummyRegister())
    assert len(result.warnings) == 2
    assert all("keine Kabel-ID" in w for w in result.warnings)


def test_build_rows_reports_register_duplicate(tmp_path):
    table = _table("cables-export.csv")
    register = tia606.KabelRegister(tmp_path / "kabel.json")
    register.add([tia606.KabelEntry(id="K-100", quelle="", ziel="", kabeltyp="", quelle_import="manuell",
                                    created="2026-09-28T10:00:00")])
    mapping = {"kabel_id": "Label"}
    result = netbox.build_rows(table, mapping, register=register)
    assert "K-100" in result.duplicates


def test_template_rows():
    rows = (netbox.CableRow(kabel_id="K-001", quelle="SW1/P1", ziel="pmx10/eno1", kabeltyp="Cat6",
                            farbe="blau", laenge="2", neu=False),)
    headers, body = netbox.template_rows(rows)
    assert headers == ["kabel_id", "quelle", "ziel", "kabeltyp"]
    assert body == [["K-001", "SW1/P1", "pmx10/eno1", "Cat6"]]


def test_save_mapping_joins_column_lists(tmp_path):
    table = _table("cables-export.csv")
    store = MappingStore(tmp_path / "mappings.json")
    mapping = {"kabel_id": "Label", "quelle": ["Side A", "Termination A"], "kabeltyp": ""}
    netbox.save_mapping(store, table, mapping)
    stored = store.load("netbox-kabel", table.headers)
    assert stored.columns["quelle"] == "Side A+Termination A"
    assert "kabeltyp" not in stored.columns
    reloaded = netbox.suggest_mapping(table, store)
    assert reloaded["quelle"] == ["Side A", "Termination A"]
