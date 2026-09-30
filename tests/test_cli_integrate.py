"""Tests für 'tapesmith integrate' (CLI-Plugin), nur mit Fake-Registry-Fabrik."""

import json

from tapesmith import integration as intg
from tapesmith.cli import main
from tapesmith.cli_cmds import integrate as integrate_cmd


def _use_fake_backend(monkeypatch):
    backend = intg.FakeRegistry()
    monkeypatch.setattr(integrate_cmd, "BACKEND_FACTORY", lambda: backend)
    return backend


def test_install_dry_run_schreibt_nichts(monkeypatch, capsys):
    backend = _use_fake_backend(monkeypatch)
    assert main(["integrate", "install", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert out.strip()
    assert backend.data == {}


def test_install_schreibt_und_zeigt_hinweis(monkeypatch, capsys):
    _use_fake_backend(monkeypatch)
    assert main(["integrate", "install"]) == 0
    out = capsys.readouterr().out
    assert "gesetzt" in out
    assert "Weitere Optionen anzeigen" in out


def test_install_zweiter_lauf_nichts_zu_tun(monkeypatch, capsys):
    _use_fake_backend(monkeypatch)
    assert main(["integrate", "install"]) == 0
    capsys.readouterr()
    assert main(["integrate", "install"]) == 0
    out = capsys.readouterr().out
    assert "Nichts zu tun" in out


def test_status_json(monkeypatch, capsys):
    _use_fake_backend(monkeypatch)
    assert main(["integrate", "install"]) == 0
    capsys.readouterr()
    assert main(["integrate", "status", "--json"]) == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data == {"context": "installiert", "uri": "installiert", "autostart": "nicht installiert"}


def test_uninstall_entfernt_alles(monkeypatch, capsys):
    _use_fake_backend(monkeypatch)
    assert main(["integrate", "install", "--context", "--uri", "--autostart"]) == 0
    capsys.readouterr()
    assert main(["integrate", "uninstall"]) == 0
    out = capsys.readouterr().out
    assert "entfernt" in out

    assert main(["integrate", "status", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data == {"context": "nicht installiert", "uri": "nicht installiert", "autostart": "nicht installiert"}


def test_install_nur_autostart(monkeypatch, capsys):
    backend = _use_fake_backend(monkeypatch)
    assert main(["integrate", "install", "--autostart"]) == 0
    capsys.readouterr()
    assert backend.get(intg.RUN_KEY, intg.RUN_VALUE) is not None
    assert backend.get(f"{intg.HKCU_CLASSES}\\tapesmith", intg.MARKER) is None


def test_status_text_ausgabe(monkeypatch, capsys):
    _use_fake_backend(monkeypatch)
    assert main(["integrate", "status"]) == 0
    out = capsys.readouterr().out
    assert "context: nicht installiert" in out
    assert "uri: nicht installiert" in out
    assert "autostart: nicht installiert" in out
