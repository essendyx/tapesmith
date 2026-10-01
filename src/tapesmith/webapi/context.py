"""Gemeinsamer Kontext aller Routen: Dienst, Token, Ereignisse, Stores.

Dazu API-Tokens (`tokens`), LAN-Freigabe (`lan`) und Begrenzung der Fehlversuche (`limiter`).
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import Request

from tapesmith import config as config_mod
from tapesmith import integration, numbering, paths
from tapesmith.device.profile import DeviceProfile, load_profile
from tapesmith.drives import DrivesBackend
from tapesmith.integration import RegistryBackend
from tapesmith.inventory import InventoryStore
from tapesmith.tape.profiles import TapeProfile, current_tape
from tapesmith.webapi import accent
from tapesmith.webapi.access import LanPolicy
from tapesmith.webapi.events import EventBroker
from tapesmith.webapi.ratelimit import FailureLimiter

if TYPE_CHECKING:  # pragma: no cover
    from tapesmith.daemon.service import PrintService
    from tapesmith.history import HistoryStore
    from tapesmith.tape.rolls import RollStore
    from tapesmith.templates.fill import CounterStore


def _default_tokens():
    """Echter Token-Speicher, spät importiert (Tests injizieren eigene Objekte mit `verify`)."""
    from tapesmith.apitokens import TokenStore

    return TokenStore()


def _mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return None


@dataclass
class ApiContext:
    service: PrintService
    home_key: str
    token: str
    broker: EventBroker
    static_dir: Path
    port: int = 0
    now: Callable[[], datetime] = datetime.now
    registry_factory: Callable[[], RegistryBackend] = integration.WinRegBackend
    ssh_runner: Callable[[list[str], float], tuple[int, str, str]] | None = None
    drives_backend: DrivesBackend | None = None
    accent_reader: Callable[[], str | None] = accent.read_accent
    # Öffnet einen Windows-URI wie ms-settings:bluetooth (Tests ersetzen ihn)
    uri_opener: Callable[[str], None] | None = None
    extras: dict = field(default_factory=dict)
    tokens: Any = field(default_factory=_default_tokens)
    lan: LanPolicy = field(default_factory=LanPolicy.disabled)
    limiter: FailureLimiter = field(default_factory=FailureLimiter)

    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _profile_cache: tuple[Any, DeviceProfile] | None = field(default=None, init=False, repr=False)
    _inventory: InventoryStore | None = field(default=None, init=False, repr=False)
    _closed: bool = field(default=False, init=False, repr=False)

    @property
    def closed(self) -> bool:
        return self._closed

    def config(self) -> dict:
        """`config.load_config()`, bei jedem Aufruf frisch."""
        return config_mod.load_config()

    def profile(self) -> DeviceProfile:
        """Geräteprofil mit Kalibrierung; neu geladen, sobald sich die Kalibrierdatei ändert."""
        path = paths.calibration_path()
        stamp = _mtime(path)
        with self._lock:
            cache = self._profile_cache
            if cache is not None and cache[0] == stamp:
                return cache[1]
        profile = load_profile(calibration_path=path)
        with self._lock:
            self._profile_cache = (stamp, profile)
        return profile

    def tape(self) -> TapeProfile:
        return current_tape(self.config())

    def history(self) -> HistoryStore:
        return self.service.history

    def rolls(self) -> RollStore:
        return self.service.rolls

    def counters(self) -> CounterStore:
        return numbering.counter_store(self.config())

    def inventory(self) -> InventoryStore:
        with self._lock:
            if self._inventory is None:
                self._inventory = InventoryStore()
            return self._inventory

    def publish(self, event: str, data: dict) -> None:
        self.broker.publish(event, data)

    def close(self) -> None:
        with self._lock:
            store, self._inventory = self._inventory, None
            self._closed = True
        if store is not None:
            store.close()


def get_ctx(request: Request) -> ApiContext:
    """FastAPI-Dependency: der Kontext der App."""
    return request.app.state.ctx
