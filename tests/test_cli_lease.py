"""Tests für `cli._needs_lease` mit `file:`-Transporten: Reservierung nur, wenn der
Befehl denselben Transport wie der (laufende) Druckdienst nutzt."""

import json
from types import SimpleNamespace

import pytest

from tapesmith import cli, paths


def write_config(data: dict) -> None:
    path = paths.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def args_for(cmd="raw", transport=None, no_daemon=False):
    return SimpleNamespace(cmd=cmd, transport=transport, no_daemon=no_daemon)


@pytest.fixture(autouse=True)
def daemon_up(monkeypatch):
    # Die globale Testumgebung setzt TAPESMITH_NO_DAEMON=1 (kein echter Dienst in Tests);
    # für diese Tests wird das gezielt aufgehoben, `daemon_running` bleibt gemockt.
    monkeypatch.delenv("TAPESMITH_NO_DAEMON", raising=False)
    monkeypatch.setattr(cli, "daemon_running", lambda **kw: True)


def test_gleicher_file_transport_ohne_explizite_angabe_braucht_lease():
    write_config({"transport": "file:C:/x/job.bin"})
    assert cli._needs_lease(args_for(transport=None)) is True


def test_gleicher_file_transport_explizit_braucht_lease():
    write_config({"transport": "file:C:/x/job.bin"})
    assert cli._needs_lease(args_for(transport="file:C:/x/job.bin")) is True


def test_abweichender_file_transport_braucht_keine_lease():
    write_config({"transport": "file:C:/x/job.bin"})
    assert cli._needs_lease(args_for(transport="file:C:/y/anders.bin")) is False


def test_com_transport_bei_config_auto_unveraendert_braucht_lease():
    write_config({"transport": "auto"})
    assert cli._needs_lease(args_for(transport="COM4")) is True


def test_no_daemon_env_verhindert_lease(monkeypatch):
    write_config({"transport": "file:C:/x/job.bin"})
    monkeypatch.setenv("TAPESMITH_NO_DAEMON", "1")
    assert cli._needs_lease(args_for(transport=None)) is False


def test_daemon_nicht_erreichbar_verhindert_lease(monkeypatch):
    write_config({"transport": "file:C:/x/job.bin"})
    monkeypatch.setattr(cli, "daemon_running", lambda **kw: False)
    assert cli._needs_lease(args_for(transport=None)) is False
