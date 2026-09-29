"""Hotfolder (`tapesmith.automation.hotfolder`): Kopiengrenzen, Entprellung, Ablage und Fehlerdateien."""

from __future__ import annotations

import base64
import json
import os
import threading
import time

import pytest

from automation_fakes import PNG_1X1, FakeClock, FakeFacade, field_json, template_summary
from tapesmith.automation import hotfolder as hf_mod
from tapesmith.automation.hotfolder import Hotfolder, create
from tapesmith.pipeline import DOUBLE_PRESS_REASON


# ---------- Hilfen ----------

def _write(path, text: str, encoding: str = "utf-8") -> None:
    path.write_text(text, encoding=encoding)


def _abgelehnt(*reasons: str) -> dict:
    return {"status": "abgelehnt", "warnings": [], "reasons": list(reasons), "history_id": None,
            "consumed_mm": 0.0, "results": [], "printer_status": None, "error": None, "queue_id": None,
            "job_key": "k", "title": "Test", "balance_text": ""}


def _bestaetigung(*reasons: str) -> dict:
    return {"status": "bestätigung_nötig", "warnings": [], "reasons": list(reasons), "history_id": None,
            "consumed_mm": 0.0, "results": [], "printer_status": None, "error": None, "queue_id": None,
            "job_key": "k", "title": "Test", "balance_text": ""}


def _ok() -> dict:
    return {"status": "ok", "warnings": [], "reasons": [], "history_id": 1, "consumed_mm": 10.0,
            "results": [], "printer_status": None, "error": None, "queue_id": None, "job_key": "k",
            "title": "Test", "balance_text": ""}


class _SeqFacade:
    """Minimale Fassade mit fest vorgegebener Antwortfolge je `print`-Aufruf (für Entprellung und
    mehrteilige Dateien: `FakeFacade` liefert immer dieselbe Antwort, hier braucht es wechselnde)."""

    def __init__(self, outcomes, *, config=None, templates=None):
        self._outcomes = list(outcomes)
        self._config = config or {}
        self._templates = templates or []
        self.printed: list[tuple[dict, dict | None, str]] = []

    def config(self) -> dict:
        return self._config

    def template_summaries(self, names=None):
        if names is None:
            return list(self._templates)
        by_name = {t["name"]: t for t in self._templates}
        return [by_name[n] for n in names if n in by_name]

    def print(self, source, options=None, *, origin):
        self.printed.append((source, options, origin))
        return self._outcomes.pop(0)


# ---------- JSON ----------

def test_json_template_wartet_auf_stabilitaet(tmp_path):
    facade = FakeFacade()
    clock = FakeClock(0.0)
    hf = Hotfolder(facade, tmp_path, settle_s=1.5, clock=clock)
    _write(tmp_path / "a.json", json.dumps({"template": "gefriergut", "values": {"inhalt": "Suppe"}}))

    results = hf.scan_once()
    assert results == []
    assert facade.printed == []

    clock.advance(1.5)
    results = hf.scan_once()
    assert len(results) == 1
    assert results[0].ok is True
    assert len(facade.printed) == 1
    source, options, origin = facade.printed[0]
    assert origin == "hotfolder"
    assert source["kind"] == "template"
    assert source["template"] == "gefriergut"
    assert not (tmp_path / "a.json").exists()
    assert (tmp_path / "done" / "a.json").exists()


def test_json_liste_zwei_objekte(tmp_path):
    facade = FakeFacade()
    hf = Hotfolder(facade, tmp_path, settle_s=0.0)
    data = [{"template": "gefriergut", "values": {"inhalt": "A"}, "copies": 2},
            {"template": "gefriergut", "values": {"inhalt": "B"}, "copies": 1}]
    _write(tmp_path / "b.json", json.dumps(data))

    results = hf.scan_once()
    assert len(results) == 1 and results[0].ok
    assert len(facade.printed) == 2
    assert facade.printed[0][1]["copies"] == 2
    assert facade.printed[1][1]["copies"] == 1


def test_json_source_options_werden_vollstaendig_weitergereicht(tmp_path):
    facade = FakeFacade()
    hf = Hotfolder(facade, tmp_path, settle_s=0.0)
    _write(tmp_path / "d.json", json.dumps({
        "source": {"kind": "text", "lines": ["Q"]},
        "options": {"cut_marks": False, "chain": True, "job_key": "job-1"},
    }))

    results = hf.scan_once()
    assert len(results) == 1 and results[0].ok
    assert len(facade.printed) == 1
    _, options, _ = facade.printed[0]
    assert options["cut_marks"] is False
    assert options["chain"] is True
    assert options["job_key"] == "job-1"
    assert options["copies"] == 1


def test_json_source_options_entprellung_unterscheidet_zusatzoptionen(tmp_path):
    facade = FakeFacade()
    hf = Hotfolder(facade, tmp_path, settle_s=0.0)
    data = [
        {"source": {"kind": "text", "lines": ["R"]}, "options": {"cut_marks": False}},
        {"source": {"kind": "text", "lines": ["R"]}, "options": {"cut_marks": True}},
    ]
    _write(tmp_path / "e.json", json.dumps(data))

    results = hf.scan_once()
    assert len(results) == 1 and results[0].ok
    assert len(facade.printed) == 2
    assert facade.printed[0][1]["cut_marks"] is False
    assert facade.printed[0][1]["copies"] == 1
    assert facade.printed[1][1]["cut_marks"] is True
    assert facade.printed[1][1]["copies"] == 1


def test_json_text_string_mit_zeilenumbruch(tmp_path):
    facade = FakeFacade()
    hf = Hotfolder(facade, tmp_path, settle_s=0.0)
    _write(tmp_path / "c.json", json.dumps({"text": "A\nB"}))

    hf.scan_once()
    assert len(facade.printed) == 1
    source = facade.printed[0][0]
    assert source == {"kind": "text", "lines": ["A", "B"]}


def test_json_kaputt_landet_in_error_mit_log(tmp_path):
    facade = FakeFacade()
    hf = Hotfolder(facade, tmp_path, settle_s=0.0)
    _write(tmp_path / "b.json", "{kaputt")

    results = hf.scan_once()
    assert len(results) == 1 and not results[0].ok
    assert facade.printed == []
    error_file = tmp_path / "error" / "b.json"
    log_file = tmp_path / "error" / "b.json.log"
    assert error_file.exists()
    assert log_file.exists()
    assert "ungültig" in log_file.read_text(encoding="utf-8")


def test_bestaetigung_noetig_wird_zum_fehler(tmp_path):
    facade = FakeFacade(outcome=_bestaetigung("Band passt nicht"))
    hf = Hotfolder(facade, tmp_path, settle_s=0.0)
    _write(tmp_path / "a.json", json.dumps({"template": "gefriergut", "values": {"inhalt": "X"}}))

    results = hf.scan_once()
    assert not results[0].ok
    assert "Rückfrage nötig" in results[0].message
    assert "confirmed" in results[0].message
    assert (tmp_path / "error" / "a.json").exists()


def test_abgelehnt_wegen_nicht_bestaetigbar(tmp_path):
    facade = FakeFacade(outcome=_abgelehnt("Quelle hotfolder kann nicht bestätigen"))
    hf = Hotfolder(facade, tmp_path, settle_s=0.0)
    _write(tmp_path / "a.json", json.dumps({"template": "gefriergut", "values": {"inhalt": "X"}}))

    results = hf.scan_once()
    assert not results[0].ok
    assert results[0].message.startswith("Abgelehnt:")
    assert "höchstens 5 Kopien je Auftrag" in results[0].message


def test_copies_ueber_grenze_ohne_druck(tmp_path):
    facade = FakeFacade()
    hf = Hotfolder(facade, tmp_path, settle_s=0.0)
    _write(tmp_path / "a.json", json.dumps({"template": "gefriergut", "values": {"inhalt": "X"},
                                            "copies": 6}))

    results = hf.scan_once()
    assert not results[0].ok
    assert "1 bis 5" in results[0].message
    assert facade.printed == []


def test_copies_ueber_grenze_mit_hoeherem_guard_limit(tmp_path):
    facade = FakeFacade(config={"guard": {"confirm_copies": 8}})
    hf = Hotfolder(facade, tmp_path, settle_s=0.0)
    _write(tmp_path / "a.json", json.dumps({"template": "gefriergut", "values": {"inhalt": "X"},
                                            "copies": 6}))

    results = hf.scan_once()
    assert results[0].ok
    assert facade.printed[0][1]["copies"] == 6


def test_vars_alias(tmp_path):
    facade = FakeFacade()
    hf = Hotfolder(facade, tmp_path, settle_s=0.0)
    _write(tmp_path / "a.json", json.dumps({"template": "gefriergut", "vars": {"inhalt": "Suppe"}}))

    hf.scan_once()
    assert facade.printed[0][0]["values"] == {"inhalt": "Suppe"}


def test_values_und_vars_zugleich_ist_fehler(tmp_path):
    facade = FakeFacade()
    hf = Hotfolder(facade, tmp_path, settle_s=0.0)
    _write(tmp_path / "a.json", json.dumps({"template": "gefriergut", "values": {"inhalt": "A"},
                                            "vars": {"inhalt": "B"}}))

    results = hf.scan_once()
    assert not results[0].ok
    assert facade.printed == []


# ---------- TXT ----------

def test_txt_drei_zeilen_und_kommentar(tmp_path):
    facade = FakeFacade()
    hf = Hotfolder(facade, tmp_path, settle_s=0.0)
    _write(tmp_path / "t.txt", "# Kommentar\nZeile 1\nZeile 2\n\nZeile 3\n")

    hf.scan_once()
    assert len(facade.printed) == 3
    assert [p[0]["lines"][0] for p in facade.printed] == ["Zeile 1", "Zeile 2", "Zeile 3"]


def test_txt_mit_template_eigentum(tmp_path):
    facade = FakeFacade()
    hf = Hotfolder(facade, tmp_path, settle_s=0.0)
    _write(tmp_path / "t.txt", "#template=eigentum\nMax Muster\nErika Musterfrau\n")

    hf.scan_once()
    assert len(facade.printed) == 2
    assert facade.printed[0][0] == {"kind": "template", "template": "eigentum",
                                    "values": {"name": "Max Muster"}}


def test_txt_debounce_innerhalb_datei(tmp_path):
    facade = FakeFacade()
    hf = Hotfolder(facade, tmp_path, settle_s=0.0)
    _write(tmp_path / "t.txt", "Mehl\nMehl\nZucker\nMehl\n")

    hf.scan_once()
    assert len(facade.printed) == 2
    assert facade.printed[0][0]["lines"] == ["Mehl"]
    assert facade.printed[0][1]["copies"] == 3
    assert facade.printed[1][0]["lines"] == ["Zucker"]
    assert facade.printed[1][1]["copies"] == 1


# ---------- CSV ----------

def test_csv_mit_template(tmp_path):
    facade = FakeFacade()
    hf = Hotfolder(facade, tmp_path, settle_s=0.0)
    _write(tmp_path / "k.csv", "#template=gefriergut\ninhalt\nSuppe\nBrot\n")

    hf.scan_once()
    assert len(facade.printed) == 2
    assert facade.printed[0][0]["values"]["inhalt"] == "Suppe"
    assert facade.printed[1][0]["values"]["inhalt"] == "Brot"


def test_csv_ohne_template_ist_fehler(tmp_path):
    facade = FakeFacade()
    hf = Hotfolder(facade, tmp_path, settle_s=0.0)
    _write(tmp_path / "k.csv", "inhalt\nSuppe\n")

    results = hf.scan_once()
    assert not results[0].ok
    assert "#template=" in results[0].message
    assert facade.printed == []


# ---------- PNG ----------

def test_png_wird_als_bildquelle_gedruckt(tmp_path):
    facade = FakeFacade()
    hf = Hotfolder(facade, tmp_path, settle_s=0.0)
    (tmp_path / "bild.png").write_bytes(PNG_1X1)

    hf.scan_once()
    assert len(facade.printed) == 1
    source = facade.printed[0][0]
    assert source["kind"] == "image"
    assert source["name"] == "bild.png"
    assert source["fit"] is True
    assert base64.b64decode(source["png"]) == PNG_1X1


# ---------- Entprellung über Dateigrenzen ----------

def test_entprellung_ueber_dateigrenzen_erfolgreich(tmp_path):
    facade = _SeqFacade([_abgelehnt(DOUBLE_PRESS_REASON), _ok()])
    sleeps: list[float] = []
    hf = Hotfolder(facade, tmp_path, settle_s=0.0, sleep=sleeps.append)
    _write(tmp_path / "a.json", json.dumps({"template": "gefriergut", "values": {"inhalt": "X"}}))

    results = hf.scan_once()
    assert results[0].ok
    assert sleeps == [1.6]
    assert len(facade.printed) == 2
    assert (tmp_path / "done" / "a.json").exists()


def test_entprellung_ueber_dateigrenzen_zweimal_ist_fehler(tmp_path):
    facade = _SeqFacade([_abgelehnt(DOUBLE_PRESS_REASON), _abgelehnt(DOUBLE_PRESS_REASON)])
    sleeps: list[float] = []
    hf = Hotfolder(facade, tmp_path, settle_s=0.0, sleep=sleeps.append)
    _write(tmp_path / "a.json", json.dumps({"template": "gefriergut", "values": {"inhalt": "X"}}))

    results = hf.scan_once()
    assert not results[0].ok
    assert sleeps == [1.6]
    assert (tmp_path / "error" / "a.json").exists()


# ---------- JSON-Liste Entprellung ----------

def test_json_liste_gleiche_objekte_werden_zusammengefasst(tmp_path):
    facade = FakeFacade()
    hf = Hotfolder(facade, tmp_path, settle_s=0.0)
    data = [{"template": "gefriergut", "values": {"inhalt": "Suppe"}, "copies": 2},
            {"template": "gefriergut", "values": {"inhalt": "Suppe"}, "copies": 3}]
    _write(tmp_path / "a.json", json.dumps(data))

    results = hf.scan_once()
    assert results[0].ok
    assert len(facade.printed) == 1
    assert facade.printed[0][1]["copies"] == 5


def test_json_liste_gleiche_objekte_ueber_grenze_ist_fehler(tmp_path):
    facade = FakeFacade()
    hf = Hotfolder(facade, tmp_path, settle_s=0.0)
    data = [{"template": "gefriergut", "values": {"inhalt": "Suppe"}, "copies": 3},
            {"template": "gefriergut", "values": {"inhalt": "Suppe"}, "copies": 3}]
    _write(tmp_path / "a.json", json.dumps(data))

    results = hf.scan_once()
    assert not results[0].ok
    assert "gleiche Aufträge" in results[0].message
    assert facade.printed == []


# ---------- Teilweise gedruckte Dateien ----------

def test_zweiter_auftrag_scheitert_dritter_nicht_aufgerufen(tmp_path):
    facade = _SeqFacade([_ok(), _abgelehnt("Testgrund")])
    hf = Hotfolder(facade, tmp_path, settle_s=0.0)
    data = [{"template": "gefriergut", "values": {"inhalt": "A"}},
            {"template": "gefriergut", "values": {"inhalt": "B"}},
            {"template": "gefriergut", "values": {"inhalt": "C"}}]
    _write(tmp_path / "a.json", json.dumps(data))

    results = hf.scan_once()
    assert not results[0].ok
    assert len(facade.printed) == 2
    assert "1 von 3 gedruckt" in results[0].message


# ---------- Größe, Namen, Sonderfälle ----------

def test_datei_zu_gross_wird_nicht_gedruckt(tmp_path):
    facade = FakeFacade()
    hf = Hotfolder(facade, tmp_path, settle_s=0.0, max_bytes=10)
    _write(tmp_path / "a.json", json.dumps({"template": "gefriergut", "values": {"inhalt": "12345678901234"}}))

    results = hf.scan_once()
    assert not results[0].ok
    assert facade.printed == []
    assert (tmp_path / "error" / "a.json").exists()


def test_namenskonflikt_in_done(tmp_path):
    facade = FakeFacade()
    hf = Hotfolder(facade, tmp_path, settle_s=0.0)
    (tmp_path / "done").mkdir()
    (tmp_path / "done" / "a.json").write_text("alt", encoding="utf-8")
    _write(tmp_path / "a.json", json.dumps({"template": "gefriergut", "values": {"inhalt": "X"}}))

    hf.scan_once()
    entries = sorted(p.name for p in (tmp_path / "done").iterdir())
    assert "a.json" in entries
    assert len(entries) == 2


def test_ignorierte_dateien_werden_nicht_angefasst(tmp_path):
    facade = FakeFacade()
    hf = Hotfolder(facade, tmp_path, settle_s=0.0)
    (tmp_path / "~$tmp.json").write_text("x", encoding="utf-8")
    (tmp_path / "x.part").write_text("x", encoding="utf-8")
    (tmp_path / "y.docx").write_text("x", encoding="utf-8")

    results = hf.scan_once()
    assert results == []
    assert facade.printed == []
    assert (tmp_path / "~$tmp.json").exists()
    assert (tmp_path / "x.part").exists()
    assert (tmp_path / "y.docx").exists()


def test_sensible_werte_nicht_im_protokoll(tmp_path):
    fields = [field_json("inhalt", "Inhalt", required=True),
             field_json("pin", "PIN", secret=True)]
    templates = [template_summary("geheim", fields)]
    facade = _SeqFacade([_abgelehnt("Testgrund")], templates=templates)
    hf = Hotfolder(facade, tmp_path, settle_s=0.0)
    _write(tmp_path / "a.json", json.dumps({"template": "geheim",
                                            "values": {"inhalt": "X", "pin": "GEHEIM123"}}))

    hf.scan_once()
    log_text = (tmp_path / "hotfolder.log").read_text(encoding="utf-8")
    error_log = (tmp_path / "error" / "a.json.log").read_text(encoding="utf-8")
    assert "GEHEIM123" not in log_text
    assert "GEHEIM123" not in error_log
    assert hf_mod.REDACTED in log_text


def test_verschieben_scheitert_einmal(tmp_path, monkeypatch):
    facade = FakeFacade()
    hf = Hotfolder(facade, tmp_path, settle_s=0.0)
    _write(tmp_path / "a.json", json.dumps({"template": "gefriergut", "values": {"inhalt": "X"}}))

    real_replace = os.replace
    calls = {"n": 0}

    def flaky_replace(src, dest):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionError("gesperrt")
        return real_replace(src, dest)

    monkeypatch.setattr(os, "replace", flaky_replace)

    hf.scan_once()
    assert len(facade.printed) == 1
    assert (tmp_path / "a.json").exists()  # noch nicht verschoben
    assert not (tmp_path / "done" / "a.json").exists()

    hf.scan_once()
    assert len(facade.printed) == 1  # kein zweiter Druck
    assert not (tmp_path / "a.json").exists()
    assert (tmp_path / "done" / "a.json").exists()


# ---------- create() ----------

def test_create_aus_ist_none():
    facade = FakeFacade()
    assert create(facade, {"hotfolder": {"enabled": False}}) is None


def test_create_an_liefert_hotfolder(tmp_path):
    facade = FakeFacade()
    result = create(facade, {"hotfolder": {"enabled": True, "dir": str(tmp_path)}})
    assert isinstance(result, Hotfolder)
    assert result.root == tmp_path


# ---------- Thread ----------

def test_thread_start_stop(tmp_path):
    facade = FakeFacade()
    hf = Hotfolder(facade, tmp_path, poll_s=0.05, settle_s=0.0)
    hf.start()
    try:
        _write(tmp_path / "a.json", json.dumps({"template": "gefriergut", "values": {"inhalt": "X"}}))
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and not facade.printed:
            time.sleep(0.02)
        assert facade.printed
    finally:
        hf.stop()
    assert hf._thread is None
    # kein hängender Thread mehr mit diesem Namen
    assert not any(t.name == "p12-hotfolder" and t.is_alive() for t in threading.enumerate())


def test_status_zaehlt_verarbeitete_und_fehlerhafte(tmp_path):
    facade = FakeFacade()
    hf = Hotfolder(facade, tmp_path, settle_s=0.0)
    _write(tmp_path / "ok.json", json.dumps({"template": "gefriergut", "values": {"inhalt": "X"}}))
    _write(tmp_path / "bad.json", "{kaputt")

    hf.scan_once()
    status = hf.status()
    assert status["name"] == "hotfolder"
    assert status["running"] is False
    assert "1 verarbeitet" in status["detail"]
    assert "1 Fehler" in status["detail"]
