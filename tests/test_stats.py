"""Tests für die Statistik zum Bandverbrauch."""

from datetime import datetime, timedelta

import pytest
from PIL import Image

from tapesmith.history import HistoryStore
from tapesmith.jobs import JobMeta
from tapesmith.stats import format_m, roll_usage, totals, usage_by
from tapesmith.tape.rolls import RollStore


def make_landscape():
    return Image.new("1", (40, 30), 255)


def _clock_from(times):
    it = iter(times)
    return lambda: next(it)


# ---------- usage_by / totals ----------

TIMES = [
    datetime(2026, 8, 15, 9, 0, 0),    # 1: 2026-08, etikett-a, cli, ok
    datetime(2026, 8, 16, 9, 0, 0),    # 2: 2026-08, etikett-b, gui, ok
    datetime(2026, 9, 10, 9, 0, 0),    # 3: 2026-09, etikett-a, cli, abgebrochen (zählt)
    datetime(2026, 9, 11, 9, 0, 0),    # 4: 2026-09, etikett-a, cli, fehler (zählt NICHT)
]


def _seeded_store(tmp_path):
    store = HistoryStore(tmp_path / "h.db", clock=_clock_from(TIMES))
    store.record(JobMeta(title="A1", template="etikett-a", source="cli"),
                landscape=make_landscape(), head=None, length_mm=10.0, tape_mm=100.0,
                copies=1, status="ok")
    store.record(JobMeta(title="B1", template="etikett-b", source="gui"),
                landscape=make_landscape(), head=None, length_mm=10.0, tape_mm=50.0,
                copies=2, status="ok")
    store.record(JobMeta(title="A2", template="etikett-a", source="cli"),
                landscape=make_landscape(), head=None, length_mm=10.0, tape_mm=30.0,
                copies=1, status="abgebrochen")
    store.record(JobMeta(title="A3", template="etikett-a", source="cli"),
                landscape=make_landscape(), head=None, length_mm=10.0, tape_mm=9999.0,
                copies=5, status="fehler")
    return store


def test_usage_by_monat_summen_und_fehler_zaehlt_nicht(tmp_path):
    with _seeded_store(tmp_path) as store:
        rows = usage_by(store, "monat")
    assert [r.key for r in rows] == ["2026-08", "2026-09"]
    aug, sep = rows
    assert (aug.jobs, aug.labels, aug.tape_mm) == (2, 3, 150.0)
    assert (sep.jobs, sep.labels, sep.tape_mm) == (1, 1, 30.0)


def test_usage_by_vorlage_sortiert_nach_band(tmp_path):
    with _seeded_store(tmp_path) as store:
        rows = usage_by(store, "vorlage")
    assert [r.key for r in rows] == ["etikett-a", "etikett-b"]
    a, b = rows
    assert (a.jobs, a.labels, a.tape_mm) == (2, 2, 130.0)
    assert (b.jobs, b.labels, b.tape_mm) == (1, 2, 50.0)


def test_usage_by_since_filtert(tmp_path):
    with _seeded_store(tmp_path) as store:
        rows = usage_by(store, "monat", since=datetime(2026, 9, 1))
    assert [r.key for r in rows] == ["2026-09"]
    assert rows[0].jobs == 1
    assert rows[0].tape_mm == 30.0


def test_usage_by_unbekannte_gruppe_raises(tmp_path):
    with _seeded_store(tmp_path) as store:
        with pytest.raises(ValueError):
            usage_by(store, "x")


def test_totals_summe(tmp_path):
    with _seeded_store(tmp_path) as store:
        rows = usage_by(store, "monat")
    total = totals(rows)
    assert total.key == "Summe"
    assert (total.jobs, total.labels, total.tape_mm) == (3, 4, 180.0)


# ---------- format_m ----------

def test_format_m():
    assert format_m(1234.0) == "1,23 m"
    assert format_m(0.0) == "0,00 m"


# ---------- iter_entries (Seiten, since/until) ----------

def test_iter_entries_liefert_alle_1200_in_reihenfolge(tmp_path):
    start = datetime(2026, 1, 1)
    times = [start + timedelta(seconds=i) for i in range(1200)]
    with HistoryStore(tmp_path / "h.db", clock=_clock_from(times)) as store:
        for i in range(1200):
            store.record(JobMeta(title=f"L{i}"), landscape=make_landscape(), head=None,
                        length_mm=1.0, tape_mm=1.0)

        entries = list(store.iter_entries(batch=500))
        assert len(entries) == 1200
        assert [e.id for e in entries] == list(range(1, 1201))
        assert all(entries[i].created <= entries[i + 1].created for i in range(len(entries) - 1))

        since = start + timedelta(seconds=600)
        since_entries = list(store.iter_entries(since=since, batch=500))
        assert len(since_entries) == 600
        assert since_entries[0].created == since

        until = start + timedelta(seconds=10)
        until_entries = list(store.iter_entries(until=until, batch=500))
        assert len(until_entries) == 10


# ---------- RollStore.all_rolls / stats.roll_usage ----------

def test_all_rolls_und_roll_usage(app_home):
    store = RollStore()
    store.new_roll("schwarz-weiss")
    store.consume(1000)
    store.mark_empty(3500)   # beendet die erste Rolle, lernt Faktor
    store.new_roll("schwarz-weiss")
    store.consume(200)

    rolls = store.all_rolls()
    assert len(rolls) == 2
    finished = [pair for pair in rolls if pair[1] is True]
    current = [pair for pair in rolls if pair[1] is False]
    assert len(finished) == 1
    assert len(current) == 1
    assert finished[0][0].used_mm == 1000
    assert current[0][0].used_mm == 200
    # nach started sortiert: die beendete Rolle wurde zuerst angelegt.
    assert rolls[0][0].started <= rolls[1][0].started

    usage = roll_usage(store)
    assert len(usage) == 2
    for u in usage:
        assert u.tape_name == "Schwarz auf Weiß (Kunststoff)"
        assert u.tape_id == "schwarz-weiss"
    finished_usage = next(u for u in usage if u.finished)
    current_usage = next(u for u in usage if not u.finished)
    assert finished_usage.used_mm == 1000
    assert current_usage.used_mm == 200


def test_roll_usage_unbekanntes_band_faellt_auf_id_zurueck(app_home):
    store = RollStore()
    store.new_roll("unbekannt")
    store.consume(50, tape_id="unbekannt")

    usage = roll_usage(store)
    assert len(usage) == 1
    assert usage[0].tape_name == "unbekannt"
