"""Tests für die CLI-Plugins 'p12 config', 'p12 backup', 'p12 nummern'."""

import json

from tapesmith import paths
from tapesmith.cli import main


def test_config_set_get_und_fehler(capsys):
    assert main(["config", "set", "queue.backoff_start_s", "45"]) == 0
    capsys.readouterr()
    assert main(["config", "get", "queue.backoff_start_s"]) == 0
    assert capsys.readouterr().out.strip() == "45"

    assert main(["config", "set", "queue.probe", "xyz"]) == 1
    err = capsys.readouterr().err
    assert err.strip()


def test_config_show_path(capsys):
    assert main(["config", "path"]) == 0
    assert capsys.readouterr().out.strip() == str(paths.config_path())

    assert main(["config", "show", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert "queue" in data
    assert data["queue"]["backoff_start_s"] == 30


def test_config_export_import(tmp_path, capsys, monkeypatch):
    assert main(["config", "set", "queue.backoff_start_s", "111"]) == 0
    capsys.readouterr()

    export_dir = tmp_path / "export"
    assert main(["config", "export", str(export_dir)]) == 0
    capsys.readouterr()

    monkeypatch.setenv("TAPESMITH_HOME", str(tmp_path / "home2"))
    assert main(["config", "import", str(export_dir), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "neu" in out


def test_backup_create_and_restore_ohne_yes_ohne_konsole(tmp_path, capsys):
    backup_dir = tmp_path / "backups"
    assert main(["backup", "create", "--dir", str(backup_dir)]) == 0
    out = capsys.readouterr().out
    assert str(backup_dir) in out

    zips = list(backup_dir.glob("*.zip"))
    assert zips

    assert main(["backup", "restore", str(zips[0])]) == 1
    err = capsys.readouterr().err
    assert "--yes" in err


def test_nummern_define_und_reserve(capsys):
    assert main(["nummern", "define", "asset", "--prefix", "HL-", "--width", "4"]) == 0
    capsys.readouterr()
    assert main(["nummern", "reserve", "asset", "--count", "2"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out == ["HL-0001", "HL-0002"]
