"""Zusatzdienste (Addons) im Druckdienst p12d: Hotfolder, MQTT, Telegram und die
Update-Prüfung (`automation.update`).

Der `AddonManager` erzeugt je Sektion aus `ADDON_SECTIONS` über eine Fabrik `(facade, cfg)` ein
Addon oder `None` (in der Konfiguration aus). Er merkt sich je Sektion eine Signatur der
Konfiguration und prüft in `housekeeping()` höchstens alle `check_s` Sekunden, ob sich eine Sektion
geändert hat; dann wird das alte Addon gestoppt und ein neues erzeugt. So wirken Änderungen an
`config.json` ohne Neustart des Dienstes.

Jede Ausnahme in Fabrik, `start`, `stop` oder `status` landet als `error` im Status und im Log; der
Dienst läuft weiter. Fehlt ein Paket, lautet der Fehler „Paket <name> fehlt: pip install <name>“.
"""

from __future__ import annotations

import importlib
import json
import logging
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol
from tapesmith.i18n import N_, _t

log = logging.getLogger(__name__)

ADDON_SECTIONS = ("hotfolder", "mqtt", "telegram", "update")

# Zusätzliche Pakete je Addon (für die Meldung bei fehlendem Import).
ADDON_PACKAGES = {"mqtt": "paho-mqtt"}

DETAIL_OFF = "aus"
DETAIL_ERROR = N_("Fehler")


class Addon(Protocol):
    name: str

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def status(self) -> dict: ...


AddonFactory = Callable[[Any, dict], "Addon | None"]


class AddonPackageMissing(RuntimeError):
    """Ein Addon braucht ein nicht installiertes Paket."""


@dataclass
class _Slot:
    addon: Any = None
    signature: str | None = None
    error: str | None = None


def _signature(cfg: dict, section: str) -> str:
    return json.dumps(cfg.get(section), sort_keys=True, default=str)


def _message(exc: BaseException) -> str:
    return str(exc) or type(exc).__name__


def _off(name: str, error: str | None = None) -> dict:
    return {"name": name, "running": False, "error": error, "detail": _t(DETAIL_ERROR) if error else DETAIL_OFF}


class AddonManager:
    """Startet, überwacht und stoppt die Addons des Dienstes."""

    def __init__(self, facade, factories: Mapping[str, AddonFactory] | None = None, *,
                 config_loader: Callable[[], dict] | None = None, clock: Callable[[], float] = time.monotonic,
                 check_s: float = 5.0):
        self.facade = facade
        self.factories = dict(default_factories() if factories is None else factories)
        self._config_loader = config_loader if config_loader is not None else facade.config
        self._clock = clock
        self._check_s = float(check_s)
        self._slots = {name: _Slot() for name in ADDON_SECTIONS}
        self._last_check: float | None = None
        self._lock = threading.RLock()

    # ---------- Lebenszyklus ----------

    def start(self) -> None:
        with self._lock:
            self._last_check = self._clock()
            try:
                cfg = self._load()
            except Exception as exc:  # noqa: BLE001: kaputte Konfiguration darf den Dienst nicht stoppen
                log.warning("Addons: Konfiguration nicht lesbar: %s", exc)
                cfg = {}
            for name in ADDON_SECTIONS:
                self._create(name, cfg)

    def housekeeping(self) -> None:
        """Höchstens alle `check_s` Sekunden: geänderte Sektionen stoppen und neu erzeugen."""
        with self._lock:
            now = self._clock()
            if self._last_check is not None and now - self._last_check < self._check_s:
                return
            self._last_check = now
            try:
                cfg = self._load()
            except Exception as exc:  # noqa: BLE001
                log.warning("Addons: Konfiguration nicht lesbar, keine Änderung: %s", exc)
                return
            for name in ADDON_SECTIONS:
                if _signature(cfg, name) == self._slots[name].signature:
                    continue
                log.info("Addon %s: Konfiguration geändert, starte neu", name)
                self._stop_slot(name)
                self._create(name, cfg)

    def stop(self) -> None:
        """Stoppt alle Addons in umgekehrter Reihenfolge; ein Fehler hält die anderen nicht auf."""
        with self._lock:
            for name in reversed(ADDON_SECTIONS):
                self._stop_slot(name)

    def statuses(self) -> list[dict]:
        """Je Sektion aus `ADDON_SECTIONS` mit Fabrik genau ein `AddonStatus` (Sektionen ohne Fabrik
        kennt dieser Manager nicht)."""
        with self._lock:
            return [self._status(name) for name in ADDON_SECTIONS if name in self.factories]

    # ---------- intern ----------

    def _load(self) -> dict:
        cfg = self._config_loader()
        if not isinstance(cfg, dict):
            raise ValueError(_t("Konfiguration ist kein Objekt"))
        return cfg

    def _create(self, name: str, cfg: dict) -> None:
        slot = self._slots[name]
        slot.signature = _signature(cfg, name)
        slot.addon = None
        slot.error = None
        factory = self.factories.get(name)
        if factory is None:
            return
        try:
            addon = factory(self.facade, cfg)
        except Exception as exc:  # noqa: BLE001
            slot.error = _message(exc)
            log.error("Addon %s: Erzeugen fehlgeschlagen: %s", name, slot.error)
            return
        if addon is None:
            return
        try:
            addon.start()
        except Exception as exc:  # noqa: BLE001
            slot.error = _message(exc)
            log.error("Addon %s: Start fehlgeschlagen: %s", name, slot.error)
            self._safe_stop(name, addon)
            return
        slot.addon = addon
        log.info("Addon %s gestartet", name)

    def _safe_stop(self, name: str, addon: Any) -> None:
        """Aufräumen nach gescheitertem Start; Fehler hier nur loggen."""
        try:
            addon.stop()
        except Exception as exc:  # noqa: BLE001
            log.warning("Addon %s: Aufräumen nach Startfehler fehlgeschlagen: %s", name, exc)

    def _stop_slot(self, name: str) -> None:
        slot = self._slots[name]
        addon, slot.addon = slot.addon, None
        if addon is None:
            return
        try:
            addon.stop()
        except Exception as exc:  # noqa: BLE001
            slot.error = _message(exc)
            log.error("Addon %s: Stoppen fehlgeschlagen: %s", name, slot.error)
            return
        slot.error = None
        log.info("Addon %s gestoppt", name)

    def _status(self, name: str) -> dict:
        slot = self._slots[name]
        if slot.addon is None:
            return _off(name, slot.error)
        try:
            status = dict(slot.addon.status())
        except Exception as exc:  # noqa: BLE001
            return _off(name, _message(exc))
        return {"name": name, "running": bool(status.get("running", False)), "error": status.get("error"),
                "detail": str(status.get("detail", ""))}


def _lazy_factory(name: str) -> AddonFactory:
    def factory(facade, cfg: dict):
        try:
            module = importlib.import_module(f"tapesmith.automation.{name}")
        except ImportError as exc:
            package = ADDON_PACKAGES.get(name) or getattr(exc, "name", None) or name
            raise AddonPackageMissing(_t("Paket {package} fehlt: pip install {package}", package=package)) from exc
        return module.create(facade, cfg)

    factory.__name__ = f"create_{name}"
    return factory


def default_factories() -> dict[str, AddonFactory]:
    """Je Sektion eine Fabrik, die `tapesmith.automation.<name>.create` erst beim Aufruf importiert."""
    return {name: _lazy_factory(name) for name in ADDON_SECTIONS}


def default_addons(service) -> AddonManager:
    from tapesmith.automation.facade import LabelFacade
    return AddonManager(LabelFacade(service))
