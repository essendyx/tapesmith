"""Tests für dataimport/mapping.py."""

import pytest

from tapesmith.dataimport.mapping import (
    ColumnMapping,
    MappingStore,
    apply_mapping,
    auto_map,
    filter_rows,
    parse_row_selection,
)
from tapesmith.dataimport.table import Table


def test_auto_map():
    fields = [("host", "Host"), ("sn", "Seriennummer"), ("slot", "Slot")]
    mapping = auto_map(["host", "Seriennummer"], fields)
    assert mapping.columns == {"host": "host", "sn": "Seriennummer", "slot": ""}


def test_auto_map_single_column_single_field():
    fields = [("host", "Host")]
    mapping = auto_map(["Rechnername"], fields)
    assert mapping.columns == {"host": "Rechnername"}


def test_auto_map_normalizes_case_and_separators():
    fields = [("sn", "Seriennummer")]
    mapping = auto_map(["Serien_Nummer"], fields)
    assert mapping.columns == {"sn": "Serien_Nummer"}


def test_mapping_store_roundtrip(tmp_path):
    store = MappingStore(tmp_path / "mappings.json")
    mapping = ColumnMapping(columns={"host": "Host", "sn": ""})
    store.save("geraete", ["Host", "SN"], mapping)
    loaded = store.load("geraete", ["Host", "SN"])
    assert loaded == mapping


def test_mapping_store_different_headers_returns_none(tmp_path):
    store = MappingStore(tmp_path / "mappings.json")
    mapping = ColumnMapping(columns={"host": "Host"})
    store.save("geraete", ["Host"], mapping)
    assert store.load("geraete", ["Anders"]) is None
    assert store.load("anderevorlage", ["Host"]) is None


def test_apply_mapping():
    table = Table(headers=("Host", "SN"), rows=(("pmx10", "274913"), ("pmx20", "401111")), source="t")
    mapping = ColumnMapping(columns={"host": "Host", "sn": "SN"})
    result = apply_mapping(table, mapping, rows=[1])
    assert result == [{"host": "pmx20", "sn": "401111"}]


def test_apply_mapping_all_rows_default():
    table = Table(headers=("Host", "SN"), rows=(("pmx10", "274913"),), source="t")
    mapping = ColumnMapping(columns={"host": "Host"})
    result = apply_mapping(table, mapping)
    assert result == [{"host": "pmx10"}]


def test_apply_mapping_unknown_column_raises():
    table = Table(headers=("Host",), rows=(("pmx10",),), source="t")
    mapping = ColumnMapping(columns={"host": "Nicht Da"})
    with pytest.raises(ValueError, match="Nicht Da"):
        apply_mapping(table, mapping)


def test_filter_rows_all_columns():
    table = Table(headers=("Host", "SN"), rows=(("pmx10", "274913"), ("pmx20", "999")), source="t")
    assert filter_rows(table, "pmx1") == [0]
    assert filter_rows(table, "") == [0, 1]


def test_filter_rows_single_column():
    table = Table(headers=("Host", "SN"), rows=(("pmx10", "274913"), ("pmx20", "999")), source="t")
    assert filter_rows(table, "999", column="SN") == [1]


def test_parse_row_selection():
    assert parse_row_selection("1-3,5", 6) == [0, 1, 2, 4]
    assert parse_row_selection("alle", 6) == [0, 1, 2, 3, 4, 5]
    assert parse_row_selection("", 6) == [0, 1, 2, 3, 4, 5]
    with pytest.raises(ValueError):
        parse_row_selection("7", 6)
