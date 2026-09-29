"""`dataimport/batch.py`: Serienauftrag-Kern mit Zeilen aus Tabelle/Serie, Zähler,
Trockenlauf-Zusammenfassung, Kontaktabzug. Kein Qt, kein Drucker."""

import json
from datetime import datetime

import pytest
from PIL import Image

from tapesmith.dataimport.batch import (
    MAX_BATCH,
    build_batch,
    commit_counters,
    contact_sheet,
    rows_from_series,
    rows_from_table,
)
from tapesmith.dataimport.mapping import ColumnMapping
from tapesmith.dataimport.table import Table
from tapesmith.device.profile import load_profile
from tapesmith.render.compose import render_label
from tapesmith.templates.fill import CounterStore, build_spec, resolve_values
from tapesmith.templates.model import template_from_dict
from tapesmith.templates.series import Counter, SeriesSpec
from tapesmith.templates.store import find_template

PROFILE = load_profile()


def _counters(path) -> CounterStore:
    return CounterStore(path / "counters.json")


# 1. rows_from_table mit Zuordnung + festen Werten; Auswahl ---------------------------------

def test_rows_from_table_mapping_fixed_and_selection():
    table = Table(headers=("Host", "Slot"), rows=(("pmx10", "SSD-1"), ("pmx20", "SSD-2")), source="t")
    mapping = ColumnMapping(columns={"host": "Host", "slot": "Slot"})
    rows = rows_from_table(table, mapping, fixed={"sn": "274913"})
    assert rows == [
        {"sn": "274913", "host": "pmx10", "slot": "SSD-1"},
        {"sn": "274913", "host": "pmx20", "slot": "SSD-2"},
    ]
    only_second = rows_from_table(table, mapping, selected=[1])
    assert only_second == [{"host": "pmx20", "slot": "SSD-2"}]


# 2. rows_from_series: ein Feld -----------------------------------------------------------

def test_rows_from_series_single_field():
    rows = rows_from_series({"slot": SeriesSpec(counters=(Counter(start="1"),), count=3, prefix="SSD-")})
    assert rows == [{"slot": "SSD-1"}, {"slot": "SSD-2"}, {"slot": "SSD-3"}]


def test_rows_from_series_parallel_fields():
    rows = rows_from_series({
        "a": SeriesSpec(counters=(Counter(start="1"),), count=2),
        "b": SeriesSpec(counters=(Counter(start="A", kind="letters"),), count=2),
    }, fixed={"c": "x"})
    assert rows == [{"c": "x", "a": "1", "b": "A"}, {"c": "x", "a": "2", "b": "B"}]


def test_rows_from_series_needs_at_least_one_spec():
    with pytest.raises(ValueError):
        rows_from_series({})


# 3. build_batch: eine Zeile ohne SN wird zum Fehler ----------------------------------------

def test_build_batch_one_missing_field_is_error_rest_ok(tmp_path):
    template = find_template("datentraeger")
    rows = [
        {"host": "pmx10", "slot": "SSD-1", "sn": "274913"},
        {"host": "pmx10", "slot": "SSD-2"},
        {"host": "pmx10", "slot": "SSD-3", "sn": "274915"},
    ]
    plan = build_batch(template, rows, PROFILE, now=datetime(2026, 1, 1), counters=_counters(tmp_path))
    assert len(plan.labels) == 2
    assert len(plan.errors) == 1
    assert plan.errors[0].startswith("Zeile 2: ")
    assert plan.rows[1].error is not None
    assert plan.rows[1].render is None

    for row_idx, values in ((0, rows[0]), (2, rows[2])):
        resolved = resolve_values(template, values, datetime(2026, 1, 1), _counters(tmp_path / "solo"))
        spec = build_spec(template, resolved.values)
        expected = render_label(spec, PROFILE)
        actual = plan.rows[row_idx].render.result
        assert actual.head.tobytes() == expected.head.tobytes()


# 4. Zähler zaehlt erst nach commit_counters ------------------------------------------------

ZAEHLER_TEMPLATE = {
    "schema_version": 2, "name": "zaehler-batch-test", "description": "",
    "fields": [{"id": "nr", "label": "Nummer", "type": "counter", "format": "{:03d}"}],
    "layout": {"lines": ["Nr {nr}"]},
}


def test_zaehler_zaehlt_erst_nach_commit(tmp_path):
    template = template_from_dict(ZAEHLER_TEMPLATE)
    counters = _counters(tmp_path)
    plan = build_batch(template, [{}, {}, {}], PROFILE, now=datetime(2026, 1, 1), counters=counters)
    assert len(plan.labels) == 3
    values = [row.render.values["nr"] for row in plan.rows]
    assert values == ["001", "002", "003"]

    counters_path = tmp_path / "counters.json"
    assert not counters_path.exists()

    commit_counters(plan, counters)
    data = json.loads(counters_path.read_text(encoding="utf-8"))
    assert data["zaehler-batch-test.nr"] == 3


# 5. summary: Kette vs. einzeln -------------------------------------------------------------

def test_summary_chain_vs_single(tmp_path):
    template = find_template("datentraeger")
    rows = [{"host": "pmx10", "slot": f"SSD-{i}", "sn": f"27491{i}"} for i in range(3)]
    plan = build_batch(template, rows, PROFILE, now=datetime(2026, 1, 1), counters=_counters(tmp_path))

    chained = plan.summary(PROFILE, chain=True)
    assert "3 Labels" in chained
    assert "ca." in chained
    assert "statt" in chained

    single = plan.summary(PROFILE, chain=False)
    assert "3 Labels" in single
    assert "einzeln" in single
    assert "statt" not in single


def test_summary_reports_error_count(tmp_path):
    template = find_template("datentraeger")
    rows = [{"host": "pmx10", "slot": "SSD-1", "sn": "274913"}, {"host": "pmx10", "slot": "SSD-2"}]
    plan = build_batch(template, rows, PROFILE, now=datetime(2026, 1, 1), counters=_counters(tmp_path))
    assert "1 Fehler" in plan.summary(PROFILE, chain=False)


# 6. contact_sheet ---------------------------------------------------------------------------

def test_contact_sheet_grows_with_labels_and_shows_errors(tmp_path):
    template = find_template("datentraeger")
    rows2 = [{"host": "pmx10", "slot": "SSD-1", "sn": "274913"},
            {"host": "pmx10", "slot": "SSD-2", "sn": "274914"}]
    rows3 = rows2 + [{"host": "pmx10", "slot": "SSD-3"}]  # dritte Zeile: SN fehlt -> Fehler
    plan2 = build_batch(template, rows2, PROFILE, now=datetime(2026, 1, 1), counters=_counters(tmp_path / "a"))
    plan3 = build_batch(template, rows3, PROFILE, now=datetime(2026, 1, 1), counters=_counters(tmp_path / "b"))

    sheet2 = contact_sheet(plan2, PROFILE)
    sheet3 = contact_sheet(plan3, PROFILE)
    assert sheet2.mode == "RGB"
    assert sheet3.height > sheet2.height

    colors = {c for _n, c in sheet3.getcolors(maxcolors=sheet3.width * sheet3.height)}
    assert (200, 0, 0) in colors  # rote Fehlerzeile


# 7. > MAX_BATCH Zeilen -> ValueError ---------------------------------------------------------

def test_more_than_max_batch_rows_raises(tmp_path):
    template = find_template("datentraeger")
    rows = [{"host": "pmx10", "slot": "SSD-1", "sn": "1"}] * (MAX_BATCH + 1)
    with pytest.raises(ValueError):
        build_batch(template, rows, PROFILE, now=datetime(2026, 1, 1), counters=_counters(tmp_path))
