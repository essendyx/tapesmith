"""CLI-Tests für 'tapesmith config set' ohne Punkt, Sektions-/Transport-Fehler und den
Hinweis auf den laufenden Druckdienst."""

import json

from tapesmith import cli, paths
from tapesmith.cli_cmds import configcmd


def test_config_set_transport_ohne_punkt(capsys):
    assert cli.main(["config", "set", "transport", "COM4"]) == 0
    out = capsys.readouterr().out
    assert "transport = 'COM4'" in out
    data = json.loads(paths.config_path().read_text(encoding="utf-8"))
    assert data["transport"] == "COM4"


def test_config_set_sektion_ohne_punkt_fehler(capsys):
    assert cli.main(["config", "set", "gui", "x"]) == 1
    err = capsys.readouterr().err
    assert "ist eine Sektion" in err


def test_config_set_transport_ungueltig(capsys):
    assert cli.main(["config", "set", "transport", "quatsch"]) == 1
    err = capsys.readouterr().err
    assert "Transport 'quatsch' ungültig" in err


def test_config_set_hinweis_wenn_dienst_laeuft(capsys, monkeypatch):
    monkeypatch.setattr(configcmd, "daemon_running", lambda **kw: True)
    assert cli.main(["config", "set", "transport", "COM5"]) == 0
    out = capsys.readouterr().out
    assert "Der Druckdienst übernimmt die Änderung vor dem nächsten Auftrag." in out


def test_config_set_kein_hinweis_ohne_dienst(capsys, monkeypatch):
    monkeypatch.setattr(configcmd, "daemon_running", lambda **kw: False)
    assert cli.main(["config", "set", "transport", "COM6"]) == 0
    out = capsys.readouterr().out
    assert "Druckdienst übernimmt" not in out


def test_config_get_web_port(capsys):
    assert cli.main(["config", "get", "web.port"]) == 0
    assert capsys.readouterr().out.strip() == "8712"
