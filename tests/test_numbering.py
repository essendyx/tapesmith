"""Tests für `numbering` (zentrale Nummernkreise)."""

import json
import threading

import pytest

from tapesmith import numbering


def test_define_reserve_peek(tmp_path):
    ranges = numbering.NumberRanges(tmp_path / "nummernkreise.json")
    ranges.define("asset", prefix="HL-", width=4)
    assert ranges.reserve("asset", 2) == ["HL-0001", "HL-0002"]
    assert ranges.peek("asset") == "HL-0003"
    with pytest.raises(ValueError):
        ranges.define("asset")


def test_reserve_parallel_keine_dubletten(tmp_path):
    ranges = numbering.NumberRanges(tmp_path / "nummernkreise.json")
    ranges.define("serie")

    all_numbers: list[str] = []
    lock = threading.Lock()

    def worker():
        for _ in range(25):
            numbers = ranges.reserve("serie", 1)
            with lock:
                all_numbers.extend(numbers)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    for t in threads:
        assert not t.is_alive()

    assert len(all_numbers) == 100
    assert len(set(all_numbers)) == 100
    assert ranges.get("serie").next == 101


def test_void(tmp_path):
    ranges = numbering.NumberRanges(tmp_path / "nummernkreise.json")
    ranges.define("asset", prefix="HL-", width=4)
    ranges.reserve("asset", 2)
    ranges.void("asset", "HL-0002", "Fehldruck")
    r = ranges.get("asset")
    assert r.voided[0]["number"] == "HL-0002"
    assert r.voided[0]["reason"] == "Fehldruck"

    with pytest.raises(ValueError):
        ranges.void("asset", "HL-0099", "nie vergeben")


def test_export_import(tmp_path):
    a = numbering.NumberRanges(tmp_path / "a.json")
    a.define("serie", prefix="S-", width=3)
    a.reserve("serie", 5)
    export_file = tmp_path / "export.json"
    a.export_json(export_file)

    b = numbering.NumberRanges(tmp_path / "b.json")
    b.define("serie", prefix="S-", width=3)
    b.reserve("serie", 20)  # b ist weiter als a

    changes = b.import_json(export_file)
    assert changes
    assert b.get("serie").next == 21  # Maximum bleibt erhalten

    a.reserve("serie", 100)  # a ist jetzt weiter als b
    a.export_json(export_file)
    b.import_json(export_file)
    assert b.get("serie").next == 106

    # Abweichendes Präfix -> ValueError, Datei unverändert.
    c = numbering.NumberRanges(tmp_path / "c.json")
    c.define("serie", prefix="ANDERS-", width=3)
    before = json.loads((tmp_path / "c.json").read_text(encoding="utf-8"))
    with pytest.raises(ValueError):
        c.import_json(export_file)
    after = json.loads((tmp_path / "c.json").read_text(encoding="utf-8"))
    assert before == after


def test_counter_store_zentraler_ordner(tmp_path):
    cfg = {"numbering": {"dir": str(tmp_path / "zentral")}}
    store = numbering.counter_store(cfg)
    store.commit("x")
    assert (tmp_path / "zentral" / "counters.json").exists()
