"""Einzelinstanz (Named Mutex), run_daemon (Stopp, Leerlauf-Ende) und main (Log-Datei)."""

import logging
import os
import threading

import pytest

from tapesmith.daemon import instance as instance_mod
from tapesmith.daemon.instance import SingleInstance, main, run_daemon
from tapesmith.ipc.pipe import PipeInUse


@pytest.fixture
def mutex_name():
    return f"Local\\Tapesmith.Test.Daemon.{os.getpid()}.{threading.get_ident()}.{id(object())}"


class FakeService:
    def __init__(self, idle=None, stop_after=None, stop_event=None):
        self.config = {}
        self.idle = idle
        self.housekeeping_calls = 0
        self.closed = False
        self.runner = None
        self._stop_after = stop_after
        self._stop_event = stop_event

    def attach_runner(self, runner):
        self.runner = runner

    def housekeeping(self):
        self.housekeeping_calls += 1
        if self._stop_after is not None and self.housekeeping_calls >= self._stop_after:
            self._stop_event.set()

    def idle_since(self):
        return self.idle

    def close(self):
        self.closed = True


class FakeServer:
    instances = []

    def __init__(self, service, *, on_shutdown=None, fail=None):
        self.service = service
        self.on_shutdown = on_shutdown
        self.started = False
        self.stopped = False
        self.clients = 0
        self.fail = fail
        FakeServer.instances.append(self)

    def start(self):
        if self.fail is not None:
            raise self.fail
        self.started = True

    def stop(self):
        self.stopped = True


class FakeRunner:
    def __init__(self):
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


# 25
def test_single_instance(mutex_name):
    first = SingleInstance(mutex_name)
    second = SingleInstance(mutex_name)
    try:
        assert first.acquire() is True
        assert second.acquire() is False
        first.release()
        assert second.acquire() is True
    finally:
        first.release()
        second.release()


# 26
def test_run_daemon_stops_on_event(mutex_name):
    stop = threading.Event()
    stop.set()
    service = FakeService()
    runner = FakeRunner()
    servers = []

    def server_factory(svc, **kw):
        server = FakeServer(svc, **kw)
        servers.append(server)
        return server

    inst = SingleInstance(mutex_name)
    rc = run_daemon(service_factory=lambda: service, server_factory=server_factory,
                    runner_factory=lambda s: runner, instance=inst, stop_event=stop, tick_s=0.01)
    assert rc == 0
    assert servers[0].started and servers[0].stopped
    assert runner.started and runner.stopped
    assert service.runner is runner and service.closed
    assert not inst.held
    probe = SingleInstance(mutex_name)
    try:
        assert probe.acquire() is True     # Mutex wieder frei
    finally:
        probe.release()


def test_shutdown_callback_stops_loop(mutex_name):
    service = FakeService()
    servers = []

    def server_factory(svc, **kw):
        server = FakeServer(svc, **kw)
        servers.append(server)
        threading.Timer(0.05, kw["on_shutdown"]).start()
        return server

    rc = run_daemon(service_factory=lambda: service, server_factory=server_factory,
                    runner_factory=lambda s: None, instance=SingleInstance(mutex_name),
                    idle_exit_s=0, tick_s=0.01)
    assert rc == 0 and service.closed and servers[0].stopped


# 27
def test_second_daemon_returns_without_server(mutex_name):
    holder = SingleInstance(mutex_name)
    assert holder.acquire()
    created = []
    try:
        rc = run_daemon(service_factory=lambda: created.append("service"),
                        server_factory=lambda *a, **k: created.append("server"),
                        instance=SingleInstance(mutex_name), stop_event=threading.Event())
        assert rc == 0
        assert created == []
    finally:
        holder.release()


def test_pipe_in_use_returns_zero(mutex_name):
    service = FakeService()
    inst = SingleInstance(mutex_name)
    rc = run_daemon(service_factory=lambda: service,
                    server_factory=lambda svc, **kw: FakeServer(svc, fail=PipeInUse("belegt"), **kw),
                    runner_factory=lambda s: None, instance=inst, stop_event=threading.Event())
    assert rc == 0 and service.closed and not inst.held


# 28
def test_idle_exit(mutex_name):
    service = FakeService(idle=0.0)
    rc = run_daemon(service_factory=lambda: service, server_factory=FakeServer,
                    runner_factory=lambda s: None, instance=SingleInstance(mutex_name),
                    stop_event=threading.Event(), idle_exit_s=5, clock=lambda: 100.0, tick_s=0.01)
    assert rc == 0
    assert service.closed and service.housekeeping_calls >= 1


def test_idle_not_long_enough_and_never(mutex_name):
    stop = threading.Event()
    service = FakeService(idle=98.0, stop_after=5, stop_event=stop)
    run_daemon(service_factory=lambda: service, server_factory=FakeServer, runner_factory=lambda s: None,
               instance=SingleInstance(mutex_name), stop_event=stop, idle_exit_s=5,
               clock=lambda: 100.0, tick_s=0.01)
    assert service.housekeeping_calls == 5     # erst der Stopp beendet

    stop2 = threading.Event()
    service2 = FakeService(idle=0.0, stop_after=5, stop_event=stop2)
    run_daemon(service_factory=lambda: service2, server_factory=FakeServer, runner_factory=lambda s: None,
               instance=SingleInstance(mutex_name), stop_event=stop2, idle_exit_s=0,
               clock=lambda: 100.0, tick_s=0.01)
    assert service2.housekeeping_calls == 5    # idle_exit_s=0: nie


def test_idle_default_from_config(mutex_name):
    stop = threading.Event()
    service = FakeService(idle=0.0, stop_after=3, stop_event=stop)
    service.config = {"daemon": {"idle_exit_s": 0}}
    run_daemon(service_factory=lambda: service, server_factory=FakeServer, runner_factory=lambda s: None,
               instance=SingleInstance(mutex_name), stop_event=stop, clock=lambda: 1e9, tick_s=0.01)
    assert service.housekeeping_calls == 3


def test_default_runner_from_config(tmp_path):
    from daemon_fakes import close_service, make_service
    from tapesmith.daemon.probe import NullProbe
    from tapesmith.daemon.runner import QueueRunner

    service, _t = make_service(tmp_path, config={"queue": {"probe": "off", "auto_retry": False}})
    try:
        runner = instance_mod.default_runner(service)
        assert isinstance(runner, QueueRunner)
        assert isinstance(runner._probe, NullProbe)
        assert runner.probe_name == "none"
    finally:
        close_service(service)


def test_main_writes_log(monkeypatch, app_home):
    seen = {}

    def fake_run_daemon(**kw):
        logging.getLogger("tapesmith.daemon").info("Testlauf gestartet")
        seen["called"] = True
        return 0

    monkeypatch.setattr(instance_mod, "run_daemon", fake_run_daemon)
    assert main(["--foreground"]) == 0
    assert seen["called"]
    log_file = app_home / "logs" / "daemon.log"
    assert "Testlauf gestartet" in log_file.read_text(encoding="utf-8")
    assert not any(isinstance(h, logging.FileHandler) for h in logging.getLogger("tapesmith").handlers)
