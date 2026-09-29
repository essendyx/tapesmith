"""Tests für `backup` (Sicherung der Zustandsdaten)."""

import json
import sqlite3
import zipfile
from datetime import datetime, timedelta

import pytest

from tapesmith import backup, config, paths
from tapesmith.history import HistoryStore
from tapesmith.jobs import JobMeta
from tapesmith.templates.store import SUFFIX, user_dir


def _make_state():
    config.save_config({"idle_timeout_s": 42})
    (paths.app_dir() / "counters.json").write_text(json.dumps({"x": 1}), encoding="utf-8")
    with HistoryStore() as store:
        store.record(JobMeta(source="cli", kind="test", title="t"), landscape=None, head=None,
                     length_mm=10.0, tape_mm=12.0, status="ok")
    (user_dir() / f"x{SUFFIX}").write_text(json.dumps({
        "schema_version": 2, "name": "x",
        "fields": [{"id": "text", "type": "input", "label": "Text"}],
        "layout": {"kind": "text", "text": "{text}"},
    }), encoding="utf-8")


def test_create_backup_enthaelt_alles_und_sqlite_lesbar(tmp_path):
    _make_state()
    zip_path = backup.create_backup(tmp_path / "backups")
    assert zip_path.exists()

    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        assert "config.json" in names
        assert "counters.json" in names
        assert "history.sqlite3" in names
        assert any(n.startswith("templates/") for n in names)
        assert "MANIFEST.json" in names
        manifest = json.loads(zf.read("MANIFEST.json").decode("utf-8"))
        assert manifest["format"] == "tapesmith-backup"

        extract_dir = tmp_path / "extracted"
        zf.extract("history.sqlite3", extract_dir)

    conn = sqlite3.connect(str(extract_dir / "history.sqlite3"))
    try:
        rows = conn.execute("SELECT title FROM jobs").fetchall()
    finally:
        conn.close()
    assert rows == [("t",)]


def test_keep_begrenzt_und_list_backups_sortiert(tmp_path):
    _make_state()
    target = tmp_path / "backups"
    times = [datetime(2026, 1, 1, 10, 0, 0), datetime(2026, 1, 2, 10, 0, 0), datetime(2026, 1, 3, 10, 0, 0)]
    for t in times:
        backup.create_backup(target, now=t, keep=2)

    backups = backup.list_backups(target)
    assert len(backups) == 2
    assert backups[0][1] == times[-1]
    assert backups[1][1] == times[-2]


def test_restore_backup(tmp_path, monkeypatch):
    _make_state()
    zip_path = backup.create_backup(tmp_path / "backups")

    home2 = tmp_path / "home2"
    monkeypatch.setenv("TAPESMITH_HOME", str(home2))

    assert not paths.config_path().exists()
    restored = backup.restore_backup(zip_path, dry_run=True)
    assert not paths.config_path().exists()
    assert any("config.json" in r for r in restored)

    restored = backup.restore_backup(zip_path)
    assert paths.config_path().exists()
    assert any("config.json" in r for r in restored)

    # Vorhandene Datei landet vor dem Überschreiben in backups/vor-restore-…
    config.save_config({"idle_timeout_s": 999})
    restored2 = backup.restore_backup(zip_path, now=datetime(2026, 5, 1, 12, 0, 0))
    assert restored2
    vor_restore = paths.app_dir() / "backups" / "vor-restore-20260501-120000" / "config.json"
    assert vor_restore.exists()
    data = json.loads(vor_restore.read_text(encoding="utf-8"))
    assert data["idle_timeout_s"] == 999

    # dry_run ändert nichts.
    before = paths.config_path().read_bytes()
    backup.restore_backup(zip_path, dry_run=True)
    assert paths.config_path().read_bytes() == before

    with pytest.raises(ValueError):
        backup.restore_backup(zip_path, running_check=lambda: True)


def test_restore_zip_slip_schutz(tmp_path):
    evil_zip = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil_zip, "w") as zf:
        zf.writestr("MANIFEST.json", json.dumps(
            {"format": "tapesmith-backup", "version": 1, "files": ["../boese.txt"]}))
        zf.writestr("../boese.txt", "böse")

    with pytest.raises(ValueError):
        backup.restore_backup(evil_zip)


@pytest.mark.parametrize("name", [
    "..\\..\\evil.txt",           # Backslash-Traversal (Windows-Trennzeichen)
    "C:\\Windows\\evil.txt",      # absoluter Windows-Pfad mit Laufwerksbuchstabe
    "C:evil.txt",                 # laufwerks-relativer Pfad (auch ohne Backslash gefährlich)
    "..\\evil.txt",
])
def test_check_zip_slip_erkennt_backslash_und_laufwerksbuchstabe(name):
    # PurePosixPath allein kennt keine Backslashes/Laufwerksbuchstaben als Trennzeichen; ohne
    # den expliziten Schutz würde `app / name` unter Windows außerhalb von
    # app_dir() liegen (verifiziert: Path("C:/temp/appdir") / "C:\\Windows\\evil.txt" ==
    # WindowsPath("C:/Windows/evil.txt")). Direkter Aufruf, weil `zipfile` Backslashes beim
    # Schreiben/Lesen auf Windows selbst schon durch `os.sep`-Ersetzung normalisiert und den
    # Fall dadurch verschleiern würde.
    with pytest.raises(ValueError):
        backup._check_zip_slip([name])


def test_restore_zip_slip_schutz_laufwerksbuchstabe_end_to_end(tmp_path):
    evil_zip = tmp_path / "evil2.zip"
    with zipfile.ZipFile(evil_zip, "w") as zf:
        zf.writestr("MANIFEST.json", json.dumps(
            {"format": "tapesmith-backup", "version": 1, "files": ["C:/Windows/evil.txt"]}))
        zf.writestr("C:/Windows/evil.txt", "böse")

    with pytest.raises(ValueError):
        backup.restore_backup(evil_zip)


def test_backup_due():
    now = datetime(2026, 1, 2, 12, 0, 0)
    assert backup.backup_due(None, now) is True
    assert backup.backup_due(now, now) is False
    assert backup.backup_due(now - timedelta(days=1), now) is True


def test_maybe_auto_backup(tmp_path):
    cfg = {"backup": {"dir": str(tmp_path / "backups"), "auto_daily": False}}
    assert backup.maybe_auto_backup(cfg) is None

    cfg = {"backup": {"dir": str(tmp_path / "backups"), "auto_daily": True}}
    now = datetime(2026, 3, 1, 8, 0, 0)
    path = backup.maybe_auto_backup(cfg, now=now)
    assert path is not None
    assert (tmp_path / "backups" / ".last_auto").exists()

    # Zweiter Aufruf am selben Tag -> None.
    same_day = datetime(2026, 3, 1, 20, 0, 0)
    assert backup.maybe_auto_backup(cfg, now=same_day) is None

    next_day = datetime(2026, 3, 2, 8, 0, 0)
    path2 = backup.maybe_auto_backup(cfg, now=next_day)
    assert path2 is not None
