"""Addon „update“ im Druckdienst: regelmäßige Update-Prüfung und bei
`update.auto_install` Installation im Leerlauf.

Erste Prüfung 5 min nach dem Start, danach alle `update.check_interval_h` Stunden. Bei
`auto_install` und verfügbarer Version: `prepare`, dann alle 60 s `idle_ok` prüfen und im Leerlauf
`start_install`. Der Thread prüft höchstens alle `poll_s` Sekunden (`tick`) und endet mit `stop()`.
Kein Addon (None), wenn `update.enabled` aus ist oder die App nicht installiert läuft."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

from tapesmith import config as config_mod
from tapesmith.config import setting
from tapesmith.update.errors import UpdateError
from tapesmith.i18n import _t

log = logging.getLogger(__name__)

FIRST_CHECK_S = 300.0
IDLE_POLL_S = 60.0
POLL_S = 5.0


class UpdateAddon:
    name = "update"

    def __init__(self, facade, cfg: dict, service, *, clock: Callable[[], float] = time.monotonic,
                 poll_s: float = POLL_S):
        self.facade = facade
        self.cfg = cfg
        self.service = service
        self.clock = clock
        self.poll_s = float(poll_s)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._next_check: float | None = None
        self._next_idle: float = 0.0
        self._pending: str | None = None
        self._error: str | None = None
        self._detail = _t("wartet auf erste Prüfung")

    # ---------- Lebenszyklus ----------

    def start(self) -> None:
        self._next_check = self.clock() + FIRST_CHECK_S
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="p12-update", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=5.0)

    def _run(self) -> None:
        while not self._stop.wait(self.poll_s):
            try:
                self.tick()
            except Exception as exc:  # noqa: BLE001 (das Addon darf den Dienst nie stören)
                self._error = str(exc) or type(exc).__name__
                log.error("Update-Addon: %s", self._error)

    # ---------- Ablauf ----------

    def tick(self) -> None:
        now = self.clock()
        if self._next_check is None:
            self._next_check = now + FIRST_CHECK_S
        if now >= self._next_check:
            self._next_check = now + float(setting(self.cfg, "update.check_interval_h")) * 3600.0
            self._check()
        if self._pending is not None and now >= self._next_idle:
            self._next_idle = now + IDLE_POLL_S
            if self.service.idle_ok(self.facade.service):
                version, self._pending = self._pending, None
                self._detail = f"installiere {version}"
                try:
                    self.service.start_install(version)
                except UpdateError as exc:
                    self._error = str(exc)
                    self._detail = _t("Installation fehlgeschlagen")

    def _check(self) -> None:
        try:
            status = self.service.check()
        except UpdateError as exc:
            self._error = str(exc)
            self._detail = _t("Prüfung fehlgeschlagen")
            return
        self._error = None
        available = status.available
        if not available:
            self._detail = "aktuell"
            return
        version = str(available["version"])
        self._detail = _t("Update {version} verfügbar", version=version)
        if not setting(self.cfg, "update.auto_install"):
            return
        if version == getattr(status, "previous", None):
            # Von dieser Version wurde zurückgestellt: nicht automatisch wieder installieren,
            # nur noch von Hand (Einstellungen bzw. `tapesmith update install`).
            self._detail = _t("Update {version} verfügbar (zurückgestellt, nur von Hand)", version=version)
            return
        try:
            self.service.prepare(version)
        except UpdateError as exc:
            self._error = str(exc)
            self._detail = _t("Bereitstellung fehlgeschlagen")
            return
        self._pending = version
        self._next_idle = self.clock()
        self._detail = _t("Update {version} bereit, wartet auf Leerlauf", version=version)

    # ---------- Status ----------

    def status(self) -> dict:
        running = self._thread is not None and self._thread.is_alive()
        try:
            state = self.service.status().state
        except Exception:  # noqa: BLE001
            state = "idle"
        return {"name": self.name, "running": running, "state": state, "error": self._error,
                "detail": self._detail}


def create(facade, cfg: dict, *, service_factory: Callable | None = None) -> UpdateAddon | None:
    """Addon oder None (`update.enabled` aus bzw. App nicht installiert)."""
    if not setting(cfg, "update.enabled"):
        return None
    if service_factory is None:
        from tapesmith.update.service import UpdateService

        service_factory = UpdateService
    loader = getattr(facade, "config", None)
    service = service_factory(loader if callable(loader) else config_mod.load_config)
    if not service.installed():
        return None
    return UpdateAddon(facade, cfg, service)
