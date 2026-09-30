"""Tests für `tapesmith stats` und `tapesmith archive`."""

import json

from PIL import Image

from tapesmith import cli, paths
from tapesmith.history import HistoryStore
from tapesmith.jobs import JobMeta
from tapesmith.tape.rolls import RollStore


def _store():
    return HistoryStore(paths.history_db_path())


def _seed_history():
    with _store() as store:
        store.record(JobMeta(title="Erstes", template="etikett-a", source="cli"),
                    landscape=Image.new("1", (40, 30), 255), head=None,
                    length_mm=10.0, tape_mm=42.0, copies=2, status="ok")
        store.record(JobMeta(title="Zweites", template="etikett-b", source="gui"),
                    landscape=Image.new("1", (40, 30), 255), head=None,
                    length_mm=10.0, tape_mm=18.0, copies=1, status="ok")


# ---------- tapesmith stats ----------

def test_stats_by_monat_tabelle_mit_summenzeile(app_home, capsys):
    _seed_history()
    assert cli.main(["stats", "--by", "monat"]) == 0
    out = capsys.readouterr().out
    assert "Schlüssel" in out
    assert "Summe" in out
    assert "3" in out   # Summe Aufträge (2) oder Labels (3) -- irgendwo in der Zeile


def test_stats_json_ist_parsebar(app_home, capsys):
    _seed_history()
    assert cli.main(["stats", "--by", "vorlage", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert isinstance(data, list)
    assert data[-1]["key"] == "Summe"
    keys = {row["key"] for row in data}
    assert "etikett-a" in keys
    assert "etikett-b" in keys


def test_stats_by_rolle_ohne_rollen(app_home, capsys):
    assert cli.main(["stats", "--by", "rolle"]) == 0
    assert "Keine Rollen erfasst" in capsys.readouterr().out


def test_stats_by_rolle_mit_daten(app_home, capsys):
    store = RollStore()
    store.new_roll("schwarz-weiss")
    store.consume(500)

    assert cli.main(["stats", "--by", "rolle"]) == 0
    out = capsys.readouterr().out
    assert "Schwarz auf Weiß" in out
    assert "nein" in out   # nicht beendet


def test_stats_since_ungueltig_ist_fehler(app_home, capsys):
    assert cli.main(["stats", "--since", "keinmonat"]) == 1
    assert "Fehler" in capsys.readouterr().err


# ---------- tapesmith archive scan ----------

def test_archive_scan_findet_secret_exit_1(app_home, capsys, tmp_path):
    secret_file = tmp_path / "secrets.txt"
    secret_file.write_text("token=abcd1234efgh", encoding="utf-8")
    assert cli.main(["archive", "scan", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "Passwort/Token-Zuweisung" in out


def test_archive_scan_ohne_secret_exit_0(app_home, capsys, tmp_path):
    harmless = tmp_path / "notiz.md"
    harmless.write_text("SN 274913", encoding="utf-8")
    assert cli.main(["archive", "scan", str(tmp_path)]) == 0
    assert "keine Secrets gefunden" in capsys.readouterr().out


# ---------- tapesmith archive add ----------

def test_archive_add_last_mit_dir(app_home, capsys, tmp_path):
    with _store() as store:
        store.record(JobMeta(title="Archiv-Test"), landscape=Image.new("1", (40, 30), 255),
                    head=Image.new("1", (96, 200), 255), length_mm=25.0, tape_mm=50.0, status="ok")

    archive_dir = tmp_path / "archiv"
    assert cli.main(["archive", "add", "last", "--dir", str(archive_dir)]) == 0
    out = capsys.readouterr().out
    assert "Archiviert" in out
    written = list(archive_dir.rglob("*.json"))
    assert len(written) == 1


def test_archive_add_ohne_dir_ist_fehler(app_home, capsys):
    with _store() as store:
        store.record(JobMeta(title="Ohne Ordner"), landscape=Image.new("1", (40, 30), 255),
                    head=None, length_mm=5.0, tape_mm=10.0, status="ok")
    assert cli.main(["archive", "add", "last"]) == 1
    assert "archive.dir nicht gesetzt" in capsys.readouterr().err
