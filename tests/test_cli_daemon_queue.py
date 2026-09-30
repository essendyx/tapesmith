"""`tapesmith daemon …` und `tapesmith queue …`: nur Fakes, kein echter Dienst, kein Prozess."""

import json

import pytest

from ipc_fakes import FakeServer
from tapesmith import cli
from tapesmith.cli_cmds import base as cmd_base
from tapesmith.cli_cmds import daemon as daemon_cmd
from tapesmith.ipc.backend import DaemonBackend, local_planner
from tapesmith.device.profile import load_profile

P = load_profile()

STATE = {"state": "verbunden", "transport": "COM4", "last_error": None, "leased": False}


def _job(job_id, position, title, state="wartet"):
    return {"id": job_id, "created": "2026-09-27T11:00:00", "source": "cli", "title": title, "state": state,
            "position": position, "attempts": 2, "next_try": "2026-09-27T12:01:00", "last_error": "offline",
            "sensitive": False, "history_id": None}


SNAPSHOT = {"jobs": [_job(1, 0, "Erster"), _job(2, 1, "Zweiter")], "paused": True, "auto_retry": True,
            "next_try": "2026-09-27T12:01:00", "probe": "connect", "waiting_reason": "Drucker nicht erreichbar"}


@pytest.fixture
def server():
    srv = FakeServer(pid=5150)
    srv.handlers["ping"] = lambda s, p: {"pid": 5150, "uptime_s": 12.0, "clients": 1, "version": "0.9"}
    srv.handlers["state"] = lambda s, p: STATE
    srv.handlers["queue.list"] = lambda s, p: SNAPSHOT
    yield srv
    srv.close()


# 25 ----------------------------------------------------------------------------------------

def test_daemon_status_not_running(monkeypatch, capsys):
    monkeypatch.setattr(daemon_cmd, "daemon_running", lambda **kw: False)
    monkeypatch.setattr(daemon_cmd, "connect_client", lambda cfg: pytest.fail("kein Verbindungsversuch"))
    assert cli.main(["daemon", "status"]) == 0
    assert "Druckdienst läuft nicht" in capsys.readouterr().out
    assert cli.main(["daemon", "status", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {"running": False}


def test_daemon_status_running(monkeypatch, capsys, server):
    monkeypatch.setattr(daemon_cmd, "daemon_running", lambda **kw: True)
    monkeypatch.setattr(daemon_cmd, "connect_client", lambda cfg: server.client())
    assert cli.main(["daemon", "status"]) == 0
    out = capsys.readouterr().out
    assert "PID 5150" in out
    assert "Drucker: verbunden (COM4)" in out
    assert "2 wartend" in out and "pausiert" in out
    assert server.methods() == ["ping", "state", "queue.list"]


def test_daemon_stop_busy_without_force_is_exit_7(monkeypatch, capsys, server):
    server.handlers["shutdown"] = lambda s, p: {"stopping": bool(p["force"])}
    monkeypatch.setattr(daemon_cmd, "daemon_running", lambda **kw: True)
    monkeypatch.setattr(daemon_cmd, "connect_client", lambda cfg: server.client())
    assert cli.main(["daemon", "stop"]) == 7
    assert "--force" in capsys.readouterr().err
    assert cli.main(["daemon", "stop", "--force"]) == 0
    assert "wird beendet" in capsys.readouterr().out
    assert server.calls("shutdown") == [{"force": False}, {"force": True}]


def test_daemon_stop_not_running(monkeypatch, capsys):
    monkeypatch.setattr(daemon_cmd, "daemon_running", lambda **kw: False)
    assert cli.main(["daemon", "stop"]) == 0
    assert "läuft nicht" in capsys.readouterr().out


# 27 ----------------------------------------------------------------------------------------

def test_daemon_start_uses_ensure_daemon(monkeypatch, capsys, server):
    seen = []

    def fake_ensure(cfg, *, client="cli", **kw):
        seen.append(client)
        return server.client()

    monkeypatch.setattr(daemon_cmd, "ensure_daemon", fake_ensure)
    assert cli.main(["daemon", "start"]) == 0
    assert "Druckdienst läuft (PID 5150)" in capsys.readouterr().out
    assert seen == ["cli"]


def test_daemon_restart_stops_waits_and_starts(monkeypatch, capsys, server):
    server.handlers["shutdown"] = lambda s, p: {"stopping": True}
    running = iter([True, True, False])
    monkeypatch.setattr(daemon_cmd, "daemon_running", lambda **kw: next(running))
    monkeypatch.setattr(daemon_cmd, "connect_client", lambda cfg: server.client())
    monkeypatch.setattr(daemon_cmd, "SLEEP", lambda s: None)
    monkeypatch.setattr(daemon_cmd, "ensure_daemon", lambda cfg, **kw: server.client())
    assert cli.main(["daemon", "restart"]) == 0
    out = capsys.readouterr().out
    assert "wird beendet" in out and "läuft (PID 5150)" in out


# 26 ----------------------------------------------------------------------------------------

@pytest.fixture
def daemon_backend(monkeypatch, server):
    backend = DaemonBackend(server.client(), planner=local_planner({}, P))
    monkeypatch.setattr(cmd_base, "BACKEND_FACTORY", lambda ctx, history: backend)
    return backend


def test_queue_list_shows_table_with_paused(daemon_backend, server, capsys):
    assert cli.main(["queue", "list"]) == 0
    out = capsys.readouterr().out
    assert "pausiert" in out and "Drucker nicht erreichbar" in out
    lines = out.splitlines()
    assert any("#id" in line and "Zustand" in line and "Titel" in line for line in lines)
    assert any("#1" in line and "Erster" in line for line in lines)
    assert any("#2" in line and "Zweiter" in line for line in lines)
    assert server.calls("queue.list") == [{"include_done": False}]


def test_queue_list_json_and_all(daemon_backend, server, capsys):
    server.handlers["queue.list"] = lambda s, p: SNAPSHOT
    assert cli.main(["queue", "list", "--all", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert [j["id"] for j in data["jobs"]] == [1, 2] and data["paused"] is True
    assert server.calls("queue.list") == [{"include_done": True}]


def test_queue_commands_send_methods(monkeypatch, server, capsys):
    server.handlers["queue.cancel"] = lambda s, p: {"ok": True}
    server.handlers["queue.duplicate"] = lambda s, p: {"id": 7}
    monkeypatch.setattr(cmd_base, "BACKEND_FACTORY",
                        lambda ctx, history: DaemonBackend(server.client(), planner=local_planner({}, P)))
    assert cli.main(["queue", "move", "2", "1"]) == 0
    assert cli.main(["queue", "cancel", "1"]) == 0
    assert cli.main(["queue", "dup", "2"]) == 0
    assert "#7" in capsys.readouterr().out
    assert cli.main(["queue", "retry"]) == 0
    assert cli.main(["queue", "retry", "2"]) == 0
    assert cli.main(["queue", "pause"]) == 0
    assert cli.main(["queue", "resume"]) == 0
    assert server.requests == [
        ("queue.move", {"id": 2, "position": 0}), ("queue.cancel", {"id": 1}), ("queue.duplicate", {"id": 2}),
        ("queue.retry", {"id": None}), ("queue.retry", {"id": 2}), ("queue.pause", {}), ("queue.resume", {})]


def test_queue_cancel_unknown_is_exit_1(monkeypatch, server, capsys):
    server.handlers["queue.cancel"] = lambda s, p: {"ok": False}
    monkeypatch.setattr(cmd_base, "BACKEND_FACTORY",
                        lambda ctx, history: DaemonBackend(server.client(), planner=local_planner({}, P)))
    assert cli.main(["queue", "cancel", "9"]) == 1
    assert "#9" in capsys.readouterr().err


def test_queue_without_daemon_is_exit_1(capsys):
    # conftest setzt TAPESMITH_NO_DAEMON=1 -> lokales Backend, keine Warteschlange
    assert cli.main(["queue", "list"]) == 1
    assert "Warteschlange braucht den Druckdienst (tapesmith daemon start)" in capsys.readouterr().err


def test_queue_move_rejects_position_zero(capsys):
    with pytest.raises(SystemExit):
        cli.main(["queue", "move", "2", "0"])
