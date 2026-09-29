"""Parallel-Druck: „GUI, CLI und Hotkey drucken parallel ohne Port-Konflikt“.

Der Druckdienst läuft im selben Prozess (PrintService mit MemoryTransport, No-op-Lock, `sleep`
ohne Wartezeit, Verlauf/Warteschlange in `tmp_path`) hinter einem echten `DaemonServer` auf der
Pipe des Test-App-Verzeichnisses. Alle Clients sprechen ihn über echte Pipe-Verbindungen an.
Kein Prozess wird gestartet, kein COM-Port geöffnet, nichts gedruckt."""

import dataclasses
import json
import threading

import pytest

from daemon_fakes import INIT_PACKET, PROFILE, close_service, make_service, request, split_jobs
from tapesmith import cli, paths
from tapesmith.daemon.server import DaemonServer
from tapesmith.device.profile import load_profile
from tapesmith.gui.services import build_services
from tapesmith.history import HistoryStore
from tapesmith.ipc.backend import DaemonBackend, local_planner
from tapesmith.ipc.client import DaemonClient
from tapesmith.lock import PrinterBusy

P = dataclasses.replace(load_profile(), leader_mm=8.0, trailer_mm=16.0)


@pytest.fixture
def daemon(tmp_path):
    """Laufender In-Process-Dienst: (service, transport, history)."""
    base = tmp_path / "dienst"
    base.mkdir()
    service, transport = make_service(base)
    server = DaemonServer(service)
    server.start()
    try:
        yield service, transport, service._test_stores[0]
    finally:
        server.stop()
        close_service(service)


@pytest.fixture
def no_local_port(monkeypatch):
    """Die CLI darf den Drucker nicht selbst öffnen, nur über den Dienst."""
    def forbidden(*args, **kw):
        raise AssertionError("CLI hat einen eigenen Transport geöffnet")

    monkeypatch.setattr(cli, "open_transport", forbidden)
    monkeypatch.setattr(cli, "SLEEP", lambda s: None)


def use_daemon_config(monkeypatch):
    monkeypatch.delenv("TAPESMITH_NO_DAEMON", raising=False)
    path = paths.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"daemon": {"spawn": False, "connect_timeout_s": 5.0}}),
                    encoding="utf-8")


def sources(history) -> list[str]:
    return sorted(entry.source for entry in history.search(""))


def assert_clean_jobs(transport, count):
    jobs = split_jobs(transport.written)
    assert len(jobs) == count
    for job in jobs:   # vollständig und nicht verschachtelt
        assert job[0] == INIT_PACKET
        assert job[-1] == PROFILE.feed_command
        assert job.count(INIT_PACKET) == 1
        assert job.count(PROFILE.feed_command) == 1


# 19
def test_gui_cli_hotkey_parallel_ueber_pipes(daemon):
    service, transport, history = daemon
    planner = local_planner({}, PROFILE)
    clients = {name: DaemonClient.connect(client=name, timeout_s=5.0) for name in ("gui", "cli", "tray")}
    backends = {name: DaemonBackend(client, planner=planner) for name, client in clients.items()}
    jobs = {"gui": ("gui", 1), "cli": ("cli", 2), "tray": ("hotkey", 3)}
    barrier = threading.Barrier(len(jobs))
    results: dict[str, object] = {}
    errors: list[BaseException] = []

    def run(name: str) -> None:
        source, mark = jobs[name]
        barrier.wait(5)
        try:
            results[name] = backends[name].execute(request(mark, source=source, title=f"Parallel {source}"))
        except BaseException as exc:  # noqa: BLE001 (wird unten geprüft)
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(name,)) for name in jobs]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(20)
    finally:
        for client in clients.values():
            client.close()
    assert not any(isinstance(e, PrinterBusy) for e in errors)
    assert errors == []
    assert {name: outcome.status for name, outcome in results.items()} == {
        "gui": "ok", "cli": "ok", "tray": "ok"}
    assert sources(history) == ["cli", "gui", "hotkey"]
    assert_clean_jobs(transport, 3)


# 20
def test_cli_druckt_ueber_den_dienst(daemon, monkeypatch, no_local_port, capsys):
    _service, transport, history = daemon
    use_daemon_config(monkeypatch)
    assert cli.main(["text", "CLI-Test"]) == 0
    assert "gedruckt" in capsys.readouterr().out
    entries = history.search("")
    assert [(e.source, e.title) for e in entries] == [("cli", "CLI-Test")]
    assert_clean_jobs(transport, 1)


# 21 (ohne Qt-Druck-Controller, direkt über das Druck-Backend der Dienste)
def test_gui_ueber_den_dienst_parallel_zur_cli(daemon, monkeypatch, no_local_port, tmp_path):
    _service, transport, history = daemon
    use_daemon_config(monkeypatch)
    svc = build_services(config={**json.loads(paths.config_path().read_text(encoding="utf-8")),
                                 "mac": "001122334455", "transport": "file:nie.bin",
                                 "idle_timeout_s": 300, "connect_timeout_s": 0.5, "guard": {}},
                         profile=P, history=HistoryStore(tmp_path / "gui.db"), use_daemon=True)
    try:
        assert svc.uses_daemon()
        barrier = threading.Barrier(2)
        results: dict = {}

        def run_gui() -> None:
            barrier.wait(5)
            results["gui"] = svc.backend.execute(request(5, source="gui", title="GUI parallel"))

        def run_cli() -> None:
            barrier.wait(5)
            results["cli"] = cli.main(["text", "CLI parallel"])

        threads = [threading.Thread(target=run_gui), threading.Thread(target=run_cli)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(20)
        assert results["gui"].status == "ok"
        assert results["cli"] == 0
        assert sources(history) == ["cli", "gui"]
        assert_clean_jobs(transport, 2)
    finally:
        svc.close()
