import sqlite3
import threading
from datetime import datetime, timedelta

import pytest
from PIL import Image, ImageChops

from tapesmith import history
from tapesmith.history import HistoryStore, STATUSES
from tapesmith.jobs import JobMeta
from tapesmith.render.qr import render_qr
from tapesmith.templates.fill import REDACTED


FIXED_NOW = datetime(2026, 9, 27, 12, 0, 0)


def fixed_clock():
    return FIXED_NOW


def make_landscape(width=40, height=30, fill=255):
    return Image.new("1", (width, height), fill)


def make_head(width=96, height=40, fill=255):
    return Image.new("1", (width, height), fill)


def test_record_and_get_round_trip(tmp_path):
    with HistoryStore(tmp_path / "h.sqlite3", clock=fixed_clock) as store:
        meta = JobMeta(source="cli", kind="text", title="Test-Label", template="etikett",
                        values={"a": "1"}, sensitive=False, spec={"lines": ["x"]})
        entry_id = store.record(meta, landscape=make_landscape(), head=make_head(),
                                 length_mm=12.0, tape_mm=36.0, copies=2, chained=True, status="läuft")
        entry = store.get(entry_id)
        assert entry.source == "cli"
        assert entry.kind == "text"
        assert entry.title == "Test-Label"
        assert entry.template == "etikett"
        assert entry.values == {"a": "1"}
        assert entry.spec == {"lines": ["x"]}
        assert entry.copies == 2
        assert entry.chained is True
        assert entry.status == "läuft"
        assert entry.error == ""
        assert entry.sensitive is False
        assert entry.has_head is True
        assert entry.created == FIXED_NOW

        store.update_status(entry_id, "ok")
        assert store.get(entry_id).status == "ok"


def test_get_missing_entry_raises_keyerror(tmp_path):
    with HistoryStore(tmp_path / "h.sqlite3", clock=fixed_clock) as store:
        with pytest.raises(KeyError):
            store.get(999)


def test_record_rejects_invalid_status(tmp_path):
    with HistoryStore(tmp_path / "h.sqlite3", clock=fixed_clock) as store:
        with pytest.raises(ValueError):
            store.record(JobMeta(), landscape=make_landscape(), head=None,
                         length_mm=1.0, tape_mm=1.0, status="mumpitz")


def test_update_status_rejects_invalid_status(tmp_path):
    with HistoryStore(tmp_path / "h.sqlite3", clock=fixed_clock) as store:
        entry_id = store.record(JobMeta(), landscape=make_landscape(), head=None,
                                 length_mm=1.0, tape_mm=1.0)
        with pytest.raises(ValueError):
            store.update_status(entry_id, "mumpitz")


def test_search_finds_substring_in_middle_of_value(tmp_path):
    with HistoryStore(tmp_path / "h.sqlite3", clock=fixed_clock) as store:
        target = store.record(JobMeta(title="Datenträger", values={"sn": "112233274913"}),
                               landscape=make_landscape(), head=None, length_mm=1.0, tape_mm=1.0)
        store.record(JobMeta(title="SN 274913", values={}),
                     landscape=make_landscape(), head=None, length_mm=1.0, tape_mm=1.0)
        store.record(JobMeta(title="Anderes", values={"x": "y"}),
                     landscape=make_landscape(), head=None, length_mm=1.0, tape_mm=1.0)

        results = store.search("274913")
        ids = {e.id for e in results}
        assert target in ids
        assert len(results) == 2

        assert store.search("999999") == []


def test_search_multiple_words_are_and_combined(tmp_path):
    with HistoryStore(tmp_path / "h.sqlite3", clock=fixed_clock) as store:
        first = store.record(JobMeta(title="Kabel Küche", values={}),
                              landscape=make_landscape(), head=None, length_mm=1.0, tape_mm=1.0)
        store.record(JobMeta(title="Kabel Keller", values={}),
                     landscape=make_landscape(), head=None, length_mm=1.0, tape_mm=1.0)

        results = store.search("Kabel Küche")
        assert {e.id for e in results} == {first}


def test_search_with_percent_or_quote_does_not_raise(tmp_path):
    with HistoryStore(tmp_path / "h.sqlite3", clock=fixed_clock) as store:
        store.record(JobMeta(title="Normal", values={}),
                     landscape=make_landscape(), head=None, length_mm=1.0, tape_mm=1.0)
        assert store.search("100%") == []
        assert store.search('sagt "hallo"') == []


def test_empty_search_returns_newest_first_and_limit_applies(tmp_path):
    with HistoryStore(tmp_path / "h.sqlite3", clock=fixed_clock) as store:
        ids = [store.record(JobMeta(title=f"Label {i}", values={}),
                             landscape=make_landscape(), head=None, length_mm=1.0, tape_mm=1.0)
                for i in range(5)]
        results = store.search("", limit=3)
        assert [e.id for e in results] == list(reversed(ids))[:3]


def test_sensitive_job_hides_head_spec_and_pixelates_thumbnail(tmp_path):
    import zxingcpp

    db_path = tmp_path / "h.sqlite3"
    with HistoryStore(db_path, clock=fixed_clock) as store:
        qr = render_qr("WIFI:T:WPA;S:Heim;P:geheim123;;", 88)
        landscape = Image.new("1", (qr.image.width + 20, 88), 255)
        landscape.paste(qr.image, (10, 0))

        entry_id = store.record(
            JobMeta(source="cli", kind="qr", title="WLAN", values={"pw": REDACTED, "ssid": "Heim"},
                    sensitive=True, spec={"qr": "geheim"}),
            landscape=landscape, head=None, length_mm=20.0, tape_mm=40.0,
        )

        assert store.head_image(entry_id) is None
        entry = store.get(entry_id)
        assert entry.spec is None
        assert entry.sensitive is True

        thumb = store.thumbnail(entry_id)
        assert thumb is not None
        assert zxingcpp.read_barcodes(thumb) == []

    assert b"geheim123" not in db_path.read_bytes()


def test_non_sensitive_head_round_trips_pixel_exact_and_thumbnail_height(tmp_path):
    with HistoryStore(tmp_path / "h.sqlite3", clock=fixed_clock) as store:
        head = make_head()
        entry_id = store.record(JobMeta(title="Kopfbild"), landscape=make_landscape(),
                                 head=head, length_mm=10.0, tape_mm=20.0)
        stored = store.head_image(entry_id)
        assert stored is not None
        assert ImageChops.difference(stored.convert("1"), head.convert("1")).getbbox() is None

        thumb = store.thumbnail(entry_id)
        assert thumb.height == history.THUMB_HEIGHT


def test_usage_since_counts_only_source_since_time_excluding_errors(tmp_path):
    with HistoryStore(tmp_path / "h.sqlite3", clock=fixed_clock) as store:
        cutoff = FIXED_NOW - timedelta(hours=1)
        store.record(JobMeta(source="api"), landscape=make_landscape(), head=None,
                     length_mm=1.0, tape_mm=10.0, status="ok")
        store.record(JobMeta(source="api"), landscape=make_landscape(), head=None,
                     length_mm=1.0, tape_mm=5.0, status="fehler")
        store.record(JobMeta(source="cli"), landscape=make_landscape(), head=None,
                     length_mm=1.0, tape_mm=100.0, status="ok")

        count, tape_mm = store.usage_since("api", cutoff)
        assert count == 1
        assert tape_mm == 10.0


def test_reprint_source_with_head(tmp_path):
    with HistoryStore(tmp_path / "h.sqlite3", clock=fixed_clock) as store:
        entry_id = store.record(JobMeta(title="Mit Kopf", template="vorlage", values={"a": "1"}),
                                 landscape=make_landscape(), head=make_head(),
                                 length_mm=1.0, tape_mm=1.0)
        source = store.reprint_source(entry_id)
        assert source.kind == "head"
        assert source.head is not None
        assert source.template == "vorlage"
        assert source.values == {"a": "1"}
        assert source.missing == ()


def test_reprint_source_sensitive_template_reports_missing_fields(tmp_path):
    with HistoryStore(tmp_path / "h.sqlite3", clock=fixed_clock) as store:
        entry_id = store.record(
            JobMeta(title="WLAN", template="wifi", values={"ssid": "Heim", "pw": REDACTED},
                    sensitive=True),
            landscape=make_landscape(), head=None, length_mm=1.0, tape_mm=1.0,
        )
        source = store.reprint_source(entry_id)
        assert source.kind == "template"
        assert source.template == "wifi"
        assert source.values == {"ssid": "Heim"}
        assert source.missing == ("pw",)


def test_reprint_source_sensitive_without_template_raises(tmp_path):
    with HistoryStore(tmp_path / "h.sqlite3", clock=fixed_clock) as store:
        entry_id = store.record(JobMeta(title="Sensibel ohne Vorlage", values={"pw": REDACTED},
                                         sensitive=True),
                                 landscape=make_landscape(), head=None, length_mm=1.0, tape_mm=1.0)
        with pytest.raises(ValueError):
            store.reprint_source(entry_id)


def test_two_stores_on_same_file_see_each_others_writes(tmp_path):
    path = tmp_path / "h.sqlite3"
    store_a = HistoryStore(path, clock=fixed_clock)
    store_b = HistoryStore(path, clock=fixed_clock)
    try:
        id_a = store_a.record(JobMeta(title="Von A"), landscape=make_landscape(), head=None,
                               length_mm=1.0, tape_mm=1.0)
        id_b = store_b.record(JobMeta(title="Von B"), landscape=make_landscape(), head=None,
                               length_mm=1.0, tape_mm=1.0)
        assert store_a.get(id_b).title == "Von B"
        assert store_b.get(id_a).title == "Von A"
    finally:
        store_a.close()
        store_b.close()


def test_write_in_thread_read_in_main_thread(tmp_path):
    with HistoryStore(tmp_path / "h.sqlite3", clock=fixed_clock) as store:
        result: dict = {}

        def writer():
            result["id"] = store.record(JobMeta(title="Aus Thread"), landscape=make_landscape(),
                                         head=None, length_mm=1.0, tape_mm=1.0)

        t = threading.Thread(target=writer)
        t.start()
        t.join()

        entry = store.get(result["id"])
        assert entry.title == "Aus Thread"


def test_last_overall_and_by_source(tmp_path):
    with HistoryStore(tmp_path / "h.sqlite3", clock=fixed_clock) as store:
        assert store.last() is None
        assert store.last("gui") is None
        store.record(JobMeta(source="cli", title="Erster"), landscape=make_landscape(), head=None,
                     length_mm=1.0, tape_mm=1.0)
        gui_id = store.record(JobMeta(source="gui", title="Zweiter"), landscape=make_landscape(),
                               head=None, length_mm=1.0, tape_mm=1.0)
        assert store.last().id == gui_id
        assert store.last("gui").id == gui_id
        assert store.last("hotkey") is None


def test_search_without_fts5_falls_back_to_like(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "FTS_SQL", "CREATE VIRTUAL TABLE jobs_fts USING nonexistent_module(x)")
    with HistoryStore(tmp_path / "h.sqlite3", clock=fixed_clock) as store:
        assert store._fts_available is False
        target = store.record(JobMeta(title="Datenträger", values={"sn": "112233274913"}),
                               landscape=make_landscape(), head=None, length_mm=1.0, tape_mm=1.0)
        results = store.search("274913")
        assert {e.id for e in results} == {target}
