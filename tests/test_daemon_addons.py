"""`daemon.addons.AddonManager` (Fake-Fabriken, Fake-Uhr, `FakeFacade`) und Einbau in run_daemon."""

import builtins
import logging
import os
import threading

import pytest

from automation_fakes import FakeClock, FakeFacade
from tapesmith.daemon import addons as addons_mod
from tapesmith.daemon.addons import ADDON_SECTIONS, AddonManager, default_addons, default_factories
from tapesmith.daemon.instance import SingleInstance, run_daemon

OFF = {"running": False, "error": None, "detail": "aus"}


class FakeAddon:
    def __init__(self, name, cfg, log, *, fail_start=None, fail_stop=None):
        self.name = name
        self.cfg = cfg
        self.log = log
        self.running = False
        self.fail_start = fail_start
        self.fail_stop = fail_stop

    def start(self):
        self.log.append(("start", self.name))
        if self.fail_start is not None:
            raise self.fail_start
        self.running = True

    def stop(self):
        self.log.append(("stop", self.name))
        if self.fail_stop is not None:
            raise self.fail_stop
        self.running = False

    def status(self):
        return {"name": self.name, "running": self.running, "error": None, "detail": "läuft"}


class Factories:
    """Fabriken je Sektion: an, wenn `cfg[sektion]["enabled"]`; zählt Aufrufe."""

    def __init__(self, log, **overrides):
        self.log = log
        self.calls = {name: 0 for name in ADDON_SECTIONS}
        self.created: dict[str, list[FakeAddon]] = {name: [] for name in ADDON_SECTIONS}
        self.overrides = overrides

    def make(self, name):
        def factory(facade, cfg):
            self.calls[name] += 1
            self.log.append(("create", name))
            if name in self.overrides:
                return self.overrides[name](facade, cfg)
            section = cfg.get(name) or {}
            if not section.get("enabled"):
                return None
            addon = FakeAddon(name, section, self.log)
            self.created[name].append(addon)
            return addon
        return factory

    def mapping(self):
        return {name: self.make(name) for name in ADDON_SECTIONS}


class Loader:
    def __init__(self, cfg):
        self.cfg = cfg
        self.calls = 0
        self.error = None

    def __call__(self):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.cfg


def _manager(cfg, **overrides):
    log = []
    factories = Factories(log, **overrides)
    loader = Loader(cfg)
    clock = FakeClock(100.0)
    manager = AddonManager(FakeFacade(config=cfg), factories.mapping(), config_loader=loader, clock=clock,
                           check_s=5.0)
    return manager, factories, loader, clock, log


def test_start_only_enabled_and_statuses():
    manager, factories, _loader, _clock, _log = _manager({"mqtt": {"enabled": True}})
    manager.start()
    assert all(factories.calls[name] == 1 for name in ADDON_SECTIONS)
    assert factories.created["mqtt"][0].running
    statuses = manager.statuses()
    assert [s["name"] for s in statuses] == ["hotfolder", "mqtt", "telegram", "update"]
    assert statuses[0] == {"name": "hotfolder", **OFF}
    assert statuses[1]["running"] is True
    assert statuses[2] == {"name": "telegram", **OFF}


def test_statuses_before_start():
    manager, *_ = _manager({})
    assert manager.statuses() == [{"name": n, **OFF} for n in ADDON_SECTIONS]


def test_factory_error_isolated(caplog):
    def broken(facade, cfg):
        raise RuntimeError("kaputt")

    manager, factories, *_ = _manager({"telegram": {"enabled": True}}, hotfolder=broken)
    with caplog.at_level(logging.ERROR, logger="tapesmith.daemon"):
        manager.start()
    by_name = {s["name"]: s for s in manager.statuses()}
    assert by_name["hotfolder"]["error"] == "kaputt"
    assert by_name["hotfolder"]["running"] is False
    assert by_name["telegram"]["running"] is True
    assert "kaputt" in caplog.text


def test_start_error_isolated():
    log = []

    def failing(facade, cfg):
        return FakeAddon("mqtt", cfg, log, fail_start=OSError("Broker weg"))

    manager, *_ = _manager({"telegram": {"enabled": True}}, mqtt=failing)
    manager.start()
    by_name = {s["name"]: s for s in manager.statuses()}
    assert by_name["mqtt"]["error"] == "Broker weg" and by_name["mqtt"]["running"] is False
    assert by_name["telegram"]["running"] is True


def test_housekeeping_respects_check_interval():
    manager, factories, loader, clock, log = _manager({"mqtt": {"enabled": True, "host": "a"},
                                                        "telegram": {"enabled": True}})
    manager.start()
    loads = loader.calls
    clock.advance(4.9)
    manager.housekeeping()
    assert loader.calls == loads

    old_mqtt = factories.created["mqtt"][0]
    telegram = factories.created["telegram"][0]
    loader.cfg = {"mqtt": {"enabled": True, "host": "b"}, "telegram": {"enabled": True}}
    clock.advance(0.2)
    log.clear()
    manager.housekeeping()
    assert loader.calls == loads + 1
    assert log == [("stop", "mqtt"), ("create", "mqtt"), ("start", "mqtt")]
    assert not old_mqtt.running
    new_mqtt = factories.created["mqtt"][1]
    assert new_mqtt.running and new_mqtt.cfg["host"] == "b"
    assert telegram.running and len(factories.created["telegram"]) == 1

    log.clear()
    manager.housekeeping()              # gleich danach: nicht erneut laden
    assert log == [] and loader.calls == loads + 1


def test_housekeeping_switch_off_and_on():
    manager, factories, loader, clock, log = _manager({"hotfolder": {"enabled": True}})
    manager.start()
    loader.cfg = {}
    clock.advance(10)
    manager.housekeeping()
    assert not factories.created["hotfolder"][0].running
    assert manager.statuses()[0] == {"name": "hotfolder", **OFF}
    loader.cfg = {"hotfolder": {"enabled": True, "dir": "x"}}
    clock.advance(10)
    manager.housekeeping()
    assert factories.created["hotfolder"][1].running


def test_housekeeping_config_error_keeps_state(caplog):
    manager, factories, loader, clock, log = _manager({"mqtt": {"enabled": True}})
    manager.start()
    loader.error = ValueError("config.json kaputt")
    clock.advance(10)
    log.clear()
    with caplog.at_level(logging.WARNING, logger="tapesmith.daemon"):
        manager.housekeeping()
    assert log == []
    assert factories.created["mqtt"][0].running
    assert "config.json kaputt" in caplog.text


def test_housekeeping_retries_failed_section():
    attempts = []

    def flaky(facade, cfg):
        attempts.append(1)
        raise RuntimeError("noch nicht")

    manager, _f, loader, clock, _log = _manager({"hotfolder": {"enabled": True}}, hotfolder=flaky)
    manager.start()
    clock.advance(10)
    manager.housekeeping()               # unverändert: nicht neu versuchen
    assert len(attempts) == 1
    loader.cfg = {"hotfolder": {"enabled": True, "dir": "neu"}}
    clock.advance(10)
    manager.housekeeping()
    assert len(attempts) == 2


def test_stop_all_even_on_error():
    log = []

    def bad_stop(facade, cfg):
        return FakeAddon("hotfolder", cfg, log, fail_stop=RuntimeError("klemmt"))

    manager, factories, *_ = _manager({"mqtt": {"enabled": True}, "telegram": {"enabled": True}},
                                      hotfolder=bad_stop)
    factories.log = log
    manager.start()
    log.clear()
    manager.stop()
    assert [e for e in log if e[0] == "stop"] == [("stop", "telegram"), ("stop", "mqtt"), ("stop", "hotfolder")]
    assert not factories.created["mqtt"][0].running
    assert not factories.created["telegram"][0].running
    by_name = {s["name"]: s for s in manager.statuses()}
    assert by_name["hotfolder"]["error"] == "klemmt"
    assert by_name["mqtt"] == {"name": "mqtt", **OFF}


def test_status_error_from_addon_status():
    class Broken(FakeAddon):
        def status(self):
            raise RuntimeError("status kaputt")

    log = []
    manager, *_ = _manager({}, mqtt=lambda f, c: Broken("mqtt", c, log))
    manager.start()
    by_name = {s["name"]: s for s in manager.statuses()}
    assert by_name["mqtt"]["error"] == "status kaputt"


def test_default_factories_placeholders_are_off():
    facade = FakeFacade()
    factories = default_factories()
    assert list(factories) == list(ADDON_SECTIONS)
    for factory in factories.values():
        assert factory(facade, {}) is None


def test_default_factories_missing_package(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "paho" or name.startswith("paho."):
            raise ImportError("No module named 'paho'")
        return real_import(name, *args, **kwargs)

    def broken_module(name, package=None):
        if name == "tapesmith.automation.mqtt":
            raise ModuleNotFoundError("No module named 'paho'", name="paho")
        return orig_import_module(name, package)

    orig_import_module = addons_mod.importlib.import_module
    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.setattr(addons_mod.importlib, "import_module", broken_module)
    manager = AddonManager(FakeFacade(), default_factories(), config_loader=lambda: {}, clock=FakeClock())
    manager.start()
    by_name = {s["name"]: s for s in manager.statuses()}
    assert "paho-mqtt" in by_name["mqtt"]["error"]
    assert by_name["mqtt"]["error"].startswith("Paket ")
    assert by_name["hotfolder"]["error"] is None


def test_default_addons_uses_label_facade(tmp_path):
    from tapesmith.automation.facade import LabelFacade
    from webapi_fakes import close_ctx, make_ctx

    ctx = make_ctx(tmp_path)
    try:
        manager = default_addons(ctx.service)
        assert isinstance(manager, AddonManager)
        assert isinstance(manager.facade, LabelFacade)
        assert manager.facade.service is ctx.service
    finally:
        close_ctx(ctx)


def test_config_loader_defaults_to_facade_config():
    facade = FakeFacade(config={"mqtt": {"enabled": True}})
    log = []
    factories = Factories(log)
    manager = AddonManager(facade, factories.mapping(), clock=FakeClock())
    manager.start()
    assert factories.created["mqtt"][0].running


def test_statuses_thread_safe_smoke():
    manager, _f, loader, clock, _log = _manager({"mqtt": {"enabled": True}})
    manager.start()
    errors = []

    def reader():
        try:
            for _ in range(200):
                assert len(manager.statuses()) == len(ADDON_SECTIONS)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    thread = threading.Thread(target=reader)
    thread.start()
    for i in range(50):
        loader.cfg = {"mqtt": {"enabled": True, "n": i}}
        clock.advance(10)
        manager.housekeeping()
    thread.join()
    assert errors == []


# ---------------- Einbau in run_daemon ----------------

@pytest.fixture
def mutex_name():
    return f"Local\\Tapesmith.Test.Addons.{os.getpid()}.{threading.get_ident()}.{id(object())}"


class LoopService:
    def __init__(self, stop_event, calls, stop_after=3):
        self.config = {}
        self.calls = calls
        self.stop_event = stop_event
        self.stop_after = stop_after
        self.n = 0

    def attach_runner(self, runner):
        pass

    def housekeeping(self):
        self.n += 1
        self.calls.append("service.housekeeping")
        if self.n >= self.stop_after:
            self.stop_event.set()

    def idle_since(self):
        return None

    def close(self):
        self.calls.append("service.close")


class PipeServer:
    def __init__(self, service, **kw):
        self.clients = 0

    def start(self):
        pass

    def stop(self):
        pass


class Recorder:
    def __init__(self, calls, prefix, **attrs):
        self.calls = calls
        self.prefix = prefix
        for key, value in attrs.items():
            setattr(self, key, value)

    def start(self):
        self.calls.append(f"{self.prefix}.start")

    def stop(self):
        self.calls.append(f"{self.prefix}.stop")

    def housekeeping(self):
        self.calls.append(f"{self.prefix}.housekeeping")


class Ctx:
    def __init__(self):
        self.extras = {}


def test_run_daemon_with_addons(mutex_name):
    stop = threading.Event()
    calls = []
    service = LoopService(stop, calls)
    web = Recorder(calls, "web", ctx=Ctx(), clients=0)
    manager = Recorder(calls, "addons")
    rc = run_daemon(service_factory=lambda: service, server_factory=PipeServer, runner_factory=lambda s: None,
                    instance=SingleInstance(mutex_name), stop_event=stop, idle_exit_s=0, tick_s=0.001,
                    web_factory=lambda s: web, addons_factory=lambda s: manager)
    assert rc == 0
    assert web.ctx.extras["addons"] is manager
    assert calls.index("web.start") < calls.index("addons.start")
    assert calls.count("addons.housekeeping") == 3
    first_hk = calls.index("service.housekeeping")
    assert calls[first_hk + 1] == "addons.housekeeping"
    assert calls.index("addons.stop") < calls.index("web.stop") < calls.index("service.close")


def test_run_daemon_addons_errors_do_not_stop_daemon(mutex_name, caplog):
    stop = threading.Event()
    calls = []
    service = LoopService(stop, calls)

    class Broken(Recorder):
        def start(self):
            raise RuntimeError("start kaputt")

        def housekeeping(self):
            raise RuntimeError("haushalt kaputt")

        def stop(self):
            calls.append("addons.stop")
            raise RuntimeError("stop kaputt")

    manager = Broken(calls, "addons")
    with caplog.at_level(logging.WARNING, logger="tapesmith.daemon"):
        rc = run_daemon(service_factory=lambda: service, server_factory=PipeServer,
                        runner_factory=lambda s: None, instance=SingleInstance(mutex_name), stop_event=stop,
                        idle_exit_s=0, tick_s=0.001, web_factory=None, addons_factory=lambda s: manager)
    assert rc == 0
    assert service.n == 3 and "service.close" in calls
    assert "start kaputt" in caplog.text


def test_run_daemon_addons_factory_raises(mutex_name):
    stop = threading.Event()
    calls = []
    service = LoopService(stop, calls)

    def factory(_service):
        raise RuntimeError("fabrik kaputt")

    rc = run_daemon(service_factory=lambda: service, server_factory=PipeServer, runner_factory=lambda s: None,
                    instance=SingleInstance(mutex_name), stop_event=stop, idle_exit_s=0, tick_s=0.001,
                    web_factory=None, addons_factory=factory)
    assert rc == 0 and service.n == 3


def test_run_daemon_without_addons(mutex_name):
    stop = threading.Event()
    calls = []
    service = LoopService(stop, calls)
    rc = run_daemon(service_factory=lambda: service, server_factory=PipeServer, runner_factory=lambda s: None,
                    instance=SingleInstance(mutex_name), stop_event=stop, idle_exit_s=0, tick_s=0.001,
                    web_factory=None, addons_factory=None)
    assert rc == 0
    assert calls.count("service.housekeeping") == 3
    assert not any(c.startswith("addons") for c in calls)


def test_default_addons_none_under_pytest():
    from tapesmith.daemon import instance as instance_mod
    assert instance_mod._default_addons(object()) is None


def test_default_addons_import_error(monkeypatch):
    from tapesmith.daemon import instance as instance_mod
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    def broken(service):
        raise ImportError("fehlt")

    monkeypatch.setattr(addons_mod, "default_addons", broken)
    assert instance_mod._default_addons(object()) is None
