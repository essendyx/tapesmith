"""Einzelinstanz und Einstieg des Druckdienstes p12d (`python -m tapesmith.daemon`).

Ein Named Mutex je Benutzer und App-Verzeichnis stellt sicher, dass nur ein Dienst läuft.
`run_daemon` baut Dienst, Warteschlangen-Läufer und Pipe-Server, ruft regelmäßig den Haushalt
(Lease-Ablauf, Tagessicherung) und endet bei Stopp, `shutdown` oder langem Leerlauf.

Nach dem Pipe-Server startet die Web-Oberfläche (HTTP-API auf 127.0.0.1, `webapi.server`).
Scheitert sie (Port belegt, Abhängigkeit fehlt), läuft der Dienst ohne Web weiter. Offene
SSE-Verbindungen (`/api/v1/events`) zählen beim Leerlauf-Ende als Client: ein offener Browser-Tab
mit der Oberfläche hält den Dienst am Leben, wie früher das Qt-Hauptfenster als Pipe-Client. Sonst
endete der Dienst unter einem offenen Tab, und der Tab verlöre seine Sitzung.

Nach der Web-Oberfläche starten die Addons (`daemon.addons.AddonManager`: Hotfolder, MQTT,
Telegram). Ihr Haushalt läuft in der Hauptschleife nach dem des Dienstes; beim Beenden werden sie
vor der Web-Oberfläche gestoppt. Fehler der Addons halten den Dienst nie an.
"""

from __future__ import annotations

import argparse
import ctypes
import logging
import os
import sys
import threading
import time
from collections.abc import Callable
from logging.handlers import RotatingFileHandler
from typing import Any

from tapesmith import modules, paths
from tapesmith.config import setting
from tapesmith.ipc.pipe import PipeInUse, daemon_mutex_name
from tapesmith.i18n import _t

log = logging.getLogger("tapesmith.daemon")

ERROR_ALREADY_EXISTS = 183
LOG_MAX_BYTES = 1_000_000
LOG_BACKUPS = 3


class SingleInstance:
    """Named Mutex (`CreateMutexW(None, True, name)`): nur der erste Aufrufer erhält ihn."""

    def __init__(self, name: str | None = None):
        self.name = name or daemon_mutex_name()
        self._handle = None
        self._k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._k32.CreateMutexW.restype = ctypes.c_void_p
        self._k32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        self._k32.ReleaseMutex.argtypes = [ctypes.c_void_p]
        self._k32.CloseHandle.argtypes = [ctypes.c_void_p]

    @property
    def held(self) -> bool:
        return self._handle is not None

    def acquire(self) -> bool:
        if self._handle is not None:
            return True
        ctypes.set_last_error(0)
        handle = self._k32.CreateMutexW(None, True, self.name)
        error = ctypes.get_last_error()
        if not handle:
            raise OSError(error, _t("CreateMutexW fehlgeschlagen"))
        if error == ERROR_ALREADY_EXISTS:
            self._k32.CloseHandle(handle)
            return False
        self._handle = handle
        return True

    def release(self) -> None:
        handle, self._handle = self._handle, None
        if handle is None:
            return
        self._k32.ReleaseMutex(handle)
        self._k32.CloseHandle(handle)


def _default_service():
    from tapesmith.daemon.service import PrintService
    return PrintService()


def _default_server(service, **kwargs):
    from tapesmith.daemon.server import DaemonServer
    return DaemonServer(service, **kwargs)


def default_runner(service) -> Any:
    """Läufer aus der Config: Backoff, automatischer Nachdruck, Erreichbarkeits-Probe."""
    from tapesmith.daemon.probe import RetryScheduler
    from tapesmith.daemon.runner import QueueRunner, backoff_from_config, probe_from_config

    cfg = service.config
    scheduler = RetryScheduler(backoff_from_config(cfg), auto_retry=bool(setting(cfg, "queue.auto_retry")))
    return QueueRunner(service, service.queue, scheduler, probe_from_config(cfg))


def _default_web(service) -> Any:
    """Web-Server aus der Config (`webapi.server.default_web`), spät importiert: fehlt FastAPI
    oder uvicorn, startet der Dienst trotzdem (nur ohne Web).

    Sicherheitsnetz: unter pytest (`PYTEST_CURRENT_TEST`) nie einen echten Port binden; Tests
    übergeben eine eigene `web_factory`."""
    try:
        from tapesmith.webapi.server import default_web
    except ImportError as exc:
        log.warning("Web-Oberfläche nicht verfügbar: %s", exc)
        return None
    if "PYTEST_CURRENT_TEST" in os.environ:
        return None
    return default_web(service)


def _default_addons(service) -> Any:
    """Addon-Manager (`daemon.addons.default_addons`), spät importiert. Unter pytest
    (`PYTEST_CURRENT_TEST`) keiner, wie bei `_default_web`; Tests übergeben `addons_factory`."""
    if "PYTEST_CURRENT_TEST" in os.environ:
        return None
    try:
        from tapesmith.daemon import addons
        return addons.default_addons(service)
    except ImportError as exc:
        log.warning("Addons nicht verfügbar: %s", exc)
        return None


def _persist_modules() -> None:
    """Ältere config.json ohne Modulliste: die erkannten Module einmal festschreiben."""
    try:
        written = modules.persist_detected_if_missing()
    except Exception:  # noqa: BLE001 (der Dienst startet auch ohne festgeschriebene Liste)
        log.exception("Modulliste nicht festgeschrieben")
        return
    if written is not None:
        log.info("Module eingeschaltet (aus vorhandenen Daten): %s", ", ".join(written) or "keine")


def run_daemon(*, service_factory: Callable[[], Any] = _default_service,
               server_factory: Callable[..., Any] = _default_server,
               runner_factory: Callable[[Any], Any] | None = None,
               instance: SingleInstance | None = None, stop_event: threading.Event | None = None,
               idle_exit_s: float | None = None, clock: Callable[[], float] = time.monotonic,
               tick_s: float = 1.0, web_factory: Callable[[Any], Any] | None = _default_web,
               addons_factory: Callable[[Any], Any] | None = _default_addons) -> int:
    instance = instance if instance is not None else SingleInstance()
    if not instance.acquire():
        log.info("Druckdienst läuft bereits, beende")
        return 0
    stop_event = stop_event if stop_event is not None else threading.Event()
    service = runner = server = web = addons = None
    _persist_modules()
    try:
        service = service_factory()
        runner = (runner_factory or default_runner)(service)
        if runner is not None:
            service.attach_runner(runner)
        server = server_factory(service, on_shutdown=stop_event.set)
        try:
            server.start()
        except PipeInUse:
            log.info("Pipe belegt, ein anderer Druckdienst läuft")
            server = None
            return 0
        if web_factory is not None:
            web = _start_web(web_factory, service)
        if addons_factory is not None:
            addons = _start_addons(addons_factory, service, web)
        if runner is not None:
            runner.start()
        idle = float(setting(service.config, "daemon.idle_exit_s")) if idle_exit_s is None else float(idle_exit_s)
        log.info("Druckdienst bereit (Leerlauf-Ende nach %s s)", idle if idle > 0 else "nie")
        while not stop_event.wait(tick_s):
            try:
                service.housekeeping()
            except Exception:  # noqa: BLE001
                log.exception("Haushalt fehlgeschlagen")
            if addons is not None:
                try:
                    addons.housekeeping()
                except Exception:  # noqa: BLE001
                    log.exception("Haushalt der Addons fehlgeschlagen")
            if idle > 0 and server.clients == 0 and _web_clients(web) == 0:
                since = service.idle_since()
                if since is not None and clock() - since >= idle:
                    log.info("Leerlauf seit %.0f s, beende", clock() - since)
                    break
        return 0
    finally:
        for step, obj in (("stop", addons), ("stop", web), ("stop", server), ("stop", runner), ("close", service)):
            if obj is None:
                continue
            try:
                getattr(obj, step)()
            except Exception:  # noqa: BLE001
                log.exception("Beenden: %s fehlgeschlagen", type(obj).__name__)
        instance.release()
        log.info("Druckdienst beendet")


def _web_clients(web: Any) -> int:
    """Offene Oberflächen (SSE-Ströme) der Web-Oberfläche; 0 ohne Web oder bei Fehlern."""
    if web is None:
        return 0
    try:
        return int(getattr(web, "clients", 0) or 0)
    except Exception:  # noqa: BLE001: ein Zählfehler darf das Leerlauf-Ende nicht verhindern
        log.exception("Web-Clients nicht lesbar")
        return 0


def _start_web(web_factory: Callable[[Any], Any], service) -> Any:
    try:
        web = web_factory(service)
        if web is not None:
            web.start()
        return web
    except (OSError, RuntimeError, ValueError) as exc:
        log.warning("Web-Oberfläche nicht verfügbar: %s", exc)
        return None


def _start_addons(addons_factory: Callable[[Any], Any], service, web: Any) -> Any:
    """Addon-Manager erzeugen, im Web-Kontext hinterlegen und starten; Fehler: Warnung."""
    try:
        manager = addons_factory(service)
    except Exception as exc:  # noqa: BLE001: Addons dürfen den Dienst nie verhindern
        log.warning("Addons nicht verfügbar: %s", exc)
        return None
    if manager is None:
        return None
    ctx = getattr(web, "ctx", None) if web is not None else None
    if ctx is not None:
        ctx.extras["addons"] = manager
    try:
        manager.start()
    except Exception as exc:  # noqa: BLE001
        log.warning("Addons: Start fehlgeschlagen: %s", exc)
    return manager


def _setup_logging(foreground: bool) -> list[logging.Handler]:
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    from tapesmith import logfiles

    logfiles.migrate_legacy_daemon_log()
    handlers: list[logging.Handler] = [
        RotatingFileHandler(logfiles.daemon_log_path(), maxBytes=LOG_MAX_BYTES,
                            backupCount=LOG_BACKUPS, encoding="utf-8")]
    if foreground:
        handlers.append(logging.StreamHandler(sys.stderr))
    root = logging.getLogger("tapesmith")
    root.setLevel(logging.INFO)
    for handler in handlers:
        handler.setFormatter(fmt)
        root.addHandler(handler)
    return handlers


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tapesmith-daemon", description=_t("Druckdienst für den Phomemo P12"))
    parser.add_argument("--foreground", action="store_true", help=_t("Log zusätzlich auf stderr ausgeben"))
    args = parser.parse_args(argv)
    root = logging.getLogger("tapesmith")
    level = root.level
    handlers = _setup_logging(args.foreground)
    try:
        return run_daemon()
    finally:
        root.setLevel(level)
        for handler in handlers:
            root.removeHandler(handler)
            handler.close()
