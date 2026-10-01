"""`tapesmith update …` über `tapesmith.cli.main` (Fake-Keyring, Fake-Dienst, Temp-Home)."""

from __future__ import annotations

import io

import pytest
import json
import sys
from datetime import datetime

from tapesmith import cli
from tapesmith import config as config_mod
from tapesmith.cli_cmds import update as update_cmd
from tapesmith.update.service import UpdateService
from update_fakes import FakeVenvRun, install_layout, make_test_key, publish_dir


def _svc_factory(tmp_path, monkeypatch, *, installed=True):
    private, keys = make_test_key()
    feed = tmp_path / "feed"
    publish_dir(feed, "0.2.1", private, notes="Neue Vorlagen")
    root = tmp_path / "root"
    exe = str(sys.executable)
    if installed:
        install_layout(root)
        exe = str(root / "versions" / "0.1.0" / "Scripts" / "pythonw.exe")
    spawned = []
    config_mod.save_config({"update": {"source": f"file:{feed}"}})

    def factory(load_config):
        return UpdateService(load_config, keys_loader=lambda: keys, root=root, spawn=spawned.append,
                             run=FakeVenvRun(), now=lambda: datetime(2026, 10, 2, 8, 0), executable=exe,
                             app_version=lambda: "0.1.0")

    monkeypatch.setattr(update_cmd, "SERVICE_FACTORY", factory)
    return spawned, root


def test_status_json(app_home, capsys):
    assert cli.main(["update", "status", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["installed"] is False
    assert data["state"] == "idle"
    assert data["channel"] == "stable"


def test_status_text(app_home, tmp_path, monkeypatch, capsys):
    _svc_factory(tmp_path, monkeypatch)
    assert cli.main(["update", "status"]) == 0
    out = capsys.readouterr().out
    assert "Version: 0.1.0 (installiert)" in out
    assert "Letzte Prüfung: noch nie" in out


def test_check_verfuegbar(app_home, tmp_path, monkeypatch, capsys):
    _svc_factory(tmp_path, monkeypatch, installed=False)
    assert cli.main(["update", "check"]) == 0
    out = capsys.readouterr().out
    assert "Update verfügbar: 0.2.1 (aktuell 0.1.0)" in out
    assert "Neue Vorlagen" in out


def test_check_quelle_nicht_erreichbar_exit_5(app_home, tmp_path, capsys):
    config_mod.save_config({"update": {"source": f"file:{tmp_path / 'gibtsnicht'}"}})
    assert cli.main(["update", "check"]) == 5
    err = capsys.readouterr().err
    assert "update.source_unreachable" in err


def test_check_ohne_schluessel_exit_1(app_home, tmp_path, monkeypatch, capsys):
    private, _keys = make_test_key()
    feed = publish_dir(tmp_path / "feed", "0.2.1", private)
    config_mod.save_config({"update": {"source": f"file:{feed}"}})
    monkeypatch.setattr(update_cmd, "SERVICE_FACTORY",
                        lambda load: UpdateService(load, keys_loader=lambda: []))
    assert cli.main(["update", "check"]) == 1
    assert "Kein vertrauenswürdiger Signaturschlüssel" in capsys.readouterr().err


def test_install_mit_yes_startet_update(app_home, tmp_path, monkeypatch, capsys):
    spawned, root = _svc_factory(tmp_path, monkeypatch)
    assert cli.main(["update", "install", "--yes"]) == 0
    assert (root / "versions" / "0.2.1" / "Scripts" / "pythonw.exe").is_file()
    assert spawned[0][1:5] == ["-m", "tapesmith.update.apply", "--version", "0.2.1"]
    assert "gestartet" in capsys.readouterr().out


def test_install_rueckfrage_nein(app_home, tmp_path, monkeypatch, capsys):
    spawned, _root = _svc_factory(tmp_path, monkeypatch)
    monkeypatch.setattr("sys.stdin", io.StringIO("n\n"))
    assert cli.main(["update", "install"]) == 1
    assert spawned == []
    assert "Abgebrochen" in capsys.readouterr().out


def test_install_nicht_installiert(app_home, tmp_path, monkeypatch, capsys):
    _svc_factory(tmp_path, monkeypatch, installed=False)
    assert cli.main(["update", "install", "--yes"]) == 1
    assert "update.not_installed" in capsys.readouterr().err


def test_rollback(app_home, tmp_path, monkeypatch, capsys):
    spawned, root = _svc_factory(tmp_path, monkeypatch)
    assert cli.main(["update", "rollback", "--yes"]) == 1
    assert "Keine vorige" in capsys.readouterr().err
    install_layout(root, versions=("0.1.0", "0.2.0"), current="0.2.0")
    monkeypatch.setattr(update_cmd, "SERVICE_FACTORY", lambda load: UpdateService(
        load, root=root, spawn=spawned.append, executable=str(root / "versions" / "0.2.0" / "Scripts" / "pythonw.exe")))
    monkeypatch.setattr("sys.stdin", io.StringIO("j\n"))
    assert cli.main(["update", "rollback"]) == 0
    assert "--rollback" in spawned[-1]
    assert "Rückstellung auf 0.1.0 gestartet" in capsys.readouterr().out


def test_kein_token_befehl_mehr(app_home, capsys):
    """Das Repository ist öffentlich: `update token` gibt es nicht mehr."""
    with pytest.raises(SystemExit):
        cli.main(["update", "token", "check"])
    capsys.readouterr()


def test_alter_token_eintrag_wird_ignoriert(app_home, tmp_path, monkeypatch, capsys):
    config_mod.save_config({"update": {"token_ref": "keyring:tapesmith/github"}})
    assert config_mod.load_config()["update"]["token_ref"] == "keyring:tapesmith/github"
    spawned, _root = _svc_factory(tmp_path, monkeypatch)
    assert cli.main(["update", "status"]) == 0


def test_list_zeigt_versionen(app_home, tmp_path, monkeypatch, capsys):
    _svc_factory(tmp_path, monkeypatch)
    assert cli.main(["update", "list"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("0.2.1") and "neu" in lines[0]
    assert lines[1].startswith("0.1.0") and "aktuell installiert" in lines[1]
    assert cli.main(["update", "list", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert [v["version"] for v in data["versions"]] == ["0.2.1", "0.1.0"]


def test_install_bestimmte_aeltere_version_mit_rueckfrage(app_home, tmp_path, monkeypatch, capsys):
    spawned, root = _svc_factory(tmp_path, monkeypatch)
    install_layout(root, versions=("0.0.9", "0.1.0"))
    monkeypatch.setattr("sys.stdin", io.StringIO("n\n"))
    assert cli.main(["update", "install", "0.0.9"]) == 1
    assert "Zurück auf 0.0.9?" in capsys.readouterr().out and spawned == []
    monkeypatch.setattr("tapesmith.update.service._default_backup", lambda cfg: tmp_path / "s.zip")
    assert cli.main(["update", "install", "0.0.9", "--yes"]) == 0
    assert spawned and spawned[0][spawned[0].index("--version") + 1] == "0.0.9"
