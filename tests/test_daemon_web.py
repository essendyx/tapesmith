"""Web-Server im Druckdienst (run_daemon), Zusatz-Empfänger und request_reload."""

import json
import logging
import os
import threading
import time

import pytest

from daemon_fakes import Events, close_service, make_service, request
from tapesmith import config, paths
from tapesmith.daemon.instance import SingleInstance, run_daemon


@pytest.fixture
def mutex_name():
    return f"Local\\Tapesmith.Test.DaemonWeb.{os.getpid()}.{threading.get_ident()}.{id(object())}"


class FakeService:
    def __init__(self):
        self.config = {}
        self.closed = False

    def attach_runner(self, runner):
        pass

    def housekeeping(self):
        pass

    def idle_since(self):
        return None

    def close(self):
        self.closed = True


class FakeServer:
    def __init__(self, service, order, **kw):
        self.order = order
        self.clients = 0

    def start(self):
        pass

    def stop(self):
        self.order.append("server")


class FakeWeb:
    def __init__(self, order, fail=None):
        self.order = order
        self.fail = fail
        self.started = False

    def start(self):
        if self.fail is not None:
            raise self.fail
        self.started = True

    def stop(self):
        self.order.append("web")


def _run(mutex_name, web_factory, order):
    stop = threading.Event()
    stop.set()
    service = FakeService()
    rc = run_daemon(service_factory=lambda: service,
                    server_factory=lambda svc, **kw: FakeServer(svc, order, **kw),
                    runner_factory=lambda s: None, instance=SingleInstance(mutex_name),
                    stop_event=stop, tick_s=0.01, web_factory=web_factory)
    return rc, service


def test_run_daemon_starts_and_stops_web_before_server(mutex_name):
    order = []
    webs = []

    def factory(service):
        web = FakeWeb(order)
        webs.append((web, service))
        return web

    rc, service = _run(mutex_name, factory, order)
    assert rc == 0
    assert webs[0][0].started and webs[0][1] is service
    assert order == ["web", "server"]


def test_run_daemon_survives_web_start_error(mutex_name, caplog):
    order = []
    caplog.set_level(logging.WARNING, logger="tapesmith.daemon")
    rc, service = _run(mutex_name, lambda s: FakeWeb(order, OSError("Port belegt")), order)
    assert rc == 0 and service.closed
    assert "server" in order
    assert any("Web-Oberfläche nicht verfügbar" in r.getMessage() for r in caplog.records)


def test_run_daemon_web_factory_none(mutex_name):
    order = []
    rc, service = _run(mutex_name, lambda s: None, order)
    assert rc == 0 and order == ["server"]


def test_default_web_import_error_gives_none(monkeypatch, caplog):
    import builtins

    from tapesmith.daemon import instance

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("tapesmith.webapi"):
            raise ImportError("kein fastapi")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    caplog.set_level(logging.WARNING, logger="tapesmith.daemon")
    assert instance._default_web(FakeService()) is None
    assert any("Web-Oberfläche" in r.getMessage() for r in caplog.records)


# ---------- Leerlauf-Ende und offene Fenster ----------

class IdleService(FakeService):
    """Seit langem untätig; stoppt nach `stop_after` Haushalts-Takten über das Stop-Event."""

    def __init__(self, stop_event, stop_after):
        super().__init__()
        self.calls = 0
        self._stop_event = stop_event
        self._stop_after = stop_after

    def housekeeping(self):
        self.calls += 1
        if self.calls >= self._stop_after:
            self._stop_event.set()

    def idle_since(self):
        return 0.0


class WebWithClients(FakeWeb):
    def __init__(self, order, clients):
        super().__init__(order)
        self.clients = clients


def _run_idle(mutex_name, web, stop_after=5):
    stop = threading.Event()
    service = IdleService(stop, stop_after)
    run_daemon(service_factory=lambda: service,
               server_factory=lambda svc, **kw: FakeServer(svc, []),
               runner_factory=lambda s: None, instance=SingleInstance(mutex_name),
               stop_event=stop, idle_exit_s=5, clock=lambda: 100.0, tick_s=0.01,
               web_factory=lambda s: web)
    return service


def test_idle_exit_waits_while_app_window_is_open(mutex_name):
    """Ein offenes Fenster (SSE-Strom) hält den Dienst am Leben, wie früher das Qt-Fenster als Pipe-Client."""
    service = _run_idle(mutex_name, WebWithClients([], clients=1))
    assert service.calls == 5          # erst der Stopp beendet, nicht der Leerlauf


def test_idle_exit_without_open_window(mutex_name):
    service = _run_idle(mutex_name, WebWithClients([], clients=0))
    assert service.calls == 1          # Leerlauf beendet sofort


def test_idle_exit_web_without_clients_attribute(mutex_name):
    service = _run_idle(mutex_name, FakeWeb([]))
    assert service.calls == 1


# ---------- PrintService.add_emitter ----------

def test_add_emitter_gets_job_events_and_bad_emitter_is_isolated(tmp_path):
    main_events = Events()
    extra = Events()
    service, transport = make_service(tmp_path, emit=main_events)

    def broken(event, data):
        raise RuntimeError("kaputt")

    service.add_emitter(broken)
    service.add_emitter(extra)
    try:
        outcome = service.submit(request(), job_key="k1")
        assert outcome.status == "ok"
        assert [d["phase"] for d in main_events.of("job")] == ["angenommen", "läuft", "fertig"]
        assert [d["phase"] for d in extra.of("job")] == ["angenommen", "läuft", "fertig"]
    finally:
        close_service(service)


def test_service_properties(tmp_path):
    service, _ = make_service(tmp_path)
    try:
        assert service.history is service._history
        assert service.rolls is service._rolls
        assert service.closed is False
    finally:
        close_service(service)
    assert service.closed is True


# ---------- request_reload ----------

class FakeRunner:
    def __init__(self):
        self.configs = []
        self._auto = True

    def reconfigure(self, cfg):
        self.configs.append(cfg)
        self._auto = bool(config.setting(cfg, "queue.auto_retry"))

    @property
    def auto_retry(self):
        return self._auto

    def next_try(self):
        return None

    probe_name = "auto"
    last_reason = ""

    def notify_online(self):
        pass

    def notify_offline(self):
        pass

    def wake(self, manual=False):
        pass

    def stop(self):
        pass


def _file_service(tmp_path, **kw):
    config.save_config({"transport": "memory"})
    return make_service(tmp_path, config_loader=config.load_config, **kw)


@pytest.mark.parametrize("with_runner", [False, True])
def test_request_reload_applies_immediately_while_locked(tmp_path, with_runner):
    service, transport = _file_service(tmp_path)
    runner = FakeRunner() if with_runner else None
    if runner is not None:
        service.attach_runner(runner)
    events = Events()
    service.add_emitter(events)
    try:
        assert service.queue_snapshot()["auto_retry"] is True
        config.set_setting("queue.auto_retry", False)
        service._job_lock.acquire()
        try:
            started = time.monotonic()
            service.request_reload()
            assert time.monotonic() - started < 5.0      # sonst wartete es auf die gehaltene Sperre
            if runner is not None:
                assert runner.configs and config.setting(runner.configs[-1], "queue.auto_retry") is False
            assert service.queue_snapshot()["auto_retry"] is False
            assert service.config["queue"]["auto_retry"] is False
        finally:
            service._job_lock.release()
        assert "state" in events.names()
        assert service.submit(request(), job_key="k").status == "ok"
        assert service.config["queue"]["auto_retry"] is False
    finally:
        close_service(service)


def test_request_reload_keeps_connection_until_next_job(tmp_path):
    service, transport = _file_service(tmp_path)
    factory = service._transport_factory
    try:
        built = factory.built
        config.save_config({"transport": "COM9"})
        service._job_lock.acquire()
        try:
            service.request_reload()
            assert service.config["transport"] == "memory"
        finally:
            service._job_lock.release()
        assert service.submit(request(), job_key="k").status == "ok"
        assert factory.built > built
        assert service.config["transport"] == "COM9"
    finally:
        close_service(service)


def test_request_reload_free_lock_rebuilds_now(tmp_path):
    service, transport = _file_service(tmp_path)
    factory = service._transport_factory
    try:
        built = factory.built
        config.save_config({"transport": "COM9"})
        service.request_reload()
        assert factory.built > built
        assert service.config["transport"] == "COM9"
    finally:
        close_service(service)


def test_request_reload_broken_config(tmp_path):
    service, transport = _file_service(tmp_path)
    events = Events()
    service.add_emitter(events)
    try:
        before = dict(service.config)
        paths.config_path().write_text("{kaputt", encoding="utf-8")
        service.request_reload()
        assert events.of("warning")
        assert "Konfiguration fehlerhaft" in events.of("warning")[-1]["text"]
        assert service.config == before
    finally:
        close_service(service)


def test_merge_keep_connection():
    from tapesmith.daemon.service import _merge_keep_connection

    old = {"transport": "COM4", "mac": "A", "ble": {"address": "x"}, "cut_pause_s": 1}
    new = {"transport": "COM9", "mac": "B", "connect_timeout_s": 3, "idle_timeout_s": 9,
           "ble": {"address": "y"}, "cut_pause_s": 5}
    merged = _merge_keep_connection(new, old)
    assert merged["transport"] == "COM4" and merged["mac"] == "A"
    assert merged["ble"] == {"address": "x"}
    assert merged["cut_pause_s"] == 5
    assert merged["connect_timeout_s"] == 3        # fehlt im alten Dict: bleibt der neue Wert
    assert "idle_timeout_s" in merged


# ---------- webapi_fakes.make_ctx: Dienst und Kontext lesen dieselbe config.json ----------

def test_make_ctx_sync_config(tmp_path):
    from webapi_fakes import close_ctx, make_ctx

    ctx = make_ctx(tmp_path)
    try:
        config.set_setting("queue.auto_retry", False)
        ctx.service.request_reload()
        assert ctx.service.config["queue"]["auto_retry"] is False
        assert ctx.config()["queue"]["auto_retry"] is False
    finally:
        close_ctx(ctx)


def test_make_ctx_config_written(tmp_path):
    from webapi_fakes import close_ctx, make_ctx

    ctx = make_ctx(tmp_path, config={"cut_pause_s": 5})
    try:
        data = json.loads(paths.config_path().read_text(encoding="utf-8"))
        assert data["cut_pause_s"] == 5 and data["transport"] == "memory"
        assert ctx.service.config["cut_pause_s"] == 5
    finally:
        close_ctx(ctx)
