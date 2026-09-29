"""Erreichbarkeits-Probe: Backoff, passive BLE-Advertisement-Prüfung, Nachdruck-Entscheidung.

Reine Logik, kein echter BLE-Scan hier: `BleAdvertisementProbe` bekommt in Tests immer
einen injizierten `scanner`. bleak wird nur im Produktionspfad (`_bleak_scan`) lazy importiert.
"""

from __future__ import annotations

import importlib.util
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol
from tapesmith.i18n import N_, _t

DEFAULT_BLE_NAMES = ("P12", "P12 PRO", "P12PRO")


class Backoff:
    def __init__(self, start_s: float = 30.0, max_s: float = 300.0, factor: float = 2.0):
        if start_s <= 0:
            raise ValueError(_t("start_s muss > 0 sein"))
        if max_s < start_s:
            raise ValueError(_t("max_s muss >= start_s sein"))
        self.start_s = start_s
        self.max_s = max_s
        self.factor = factor

    def delay(self, attempts: int) -> float:
        attempts = max(1, attempts)
        value = self.start_s * (self.factor ** (attempts - 1))
        return min(value, self.max_s)


class ReachabilityProbe(Protocol):
    name: str

    def check(self) -> bool | None: ...


class NullProbe:
    name = "none"

    def check(self) -> None:
        return None


def _normalize_address(address: str) -> str:
    return address.replace(":", "").casefold()


def _bleak_scan(timeout: float) -> list[tuple[str | None, str]]:
    """Nur Produktion: echter BLE-Scan in eigenem Thread mit eigener Eventloop."""
    import asyncio

    from bleak import BleakScanner

    result: list[tuple[str | None, str]] = []
    error: list[BaseException] = []

    def run() -> None:
        try:
            devices = asyncio.run(BleakScanner.discover(timeout=timeout))
            result.extend((d.name, d.address) for d in devices)
        except BaseException as exc:  # noqa: BLE001 (an check() weiterreichen)
            error.append(exc)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join()
    if error:
        raise error[0]
    return result


class BleAdvertisementProbe:
    name = "ble"

    def __init__(self, names: Sequence[str] = DEFAULT_BLE_NAMES, address: str | None = None,
                 timeout_s: float = 4.0,
                 scanner: Callable[[float], list[tuple[str | None, str]]] | None = None):
        self._names = tuple(names)
        self._address = address
        self._timeout_s = timeout_s
        self._scanner = scanner if scanner is not None else _bleak_scan

    def _matches(self, name: str | None, address: str | None) -> bool:
        if self._address is not None and address is not None:
            if _normalize_address(address) == _normalize_address(self._address):
                return True
        if name is not None:
            folded = name.casefold()
            for candidate in self._names:
                cf = candidate.casefold()
                if folded == cf or folded.startswith(cf):
                    return True
        return False

    def check(self) -> bool | None:
        try:
            devices = self._scanner(self._timeout_s)
        except Exception:
            return None
        return any(self._matches(name, address) for name, address in devices)


def bleak_available() -> bool:
    return importlib.util.find_spec("bleak") is not None


def make_probe(mode: str, *, names: Sequence[str] = DEFAULT_BLE_NAMES, address: str | None = None,
                timeout_s: float = 4.0) -> ReachabilityProbe:
    if mode == "auto":
        return BleAdvertisementProbe(names=names, address=address, timeout_s=timeout_s) \
            if bleak_available() else NullProbe()
    if mode == "ble":
        return BleAdvertisementProbe(names=names, address=address, timeout_s=timeout_s)
    if mode in ("connect", "off"):
        return NullProbe()
    raise ValueError(_t("Unbekannter Probe-Modus '{mode}'", mode=mode))


@dataclass(frozen=True)
class RetryDecision:
    action: str
    wait_s: float
    reason: str


class RetryScheduler:
    """Entscheidet, wann der Dienst wieder versucht (reine Logik, Uhr injizierbar)."""

    NO_JOBS_WAIT_S = 3600.0
    AUTO_OFF_WAIT_S = 3600.0
    AUTO_OFF_REASON = N_("Automatischer Nachdruck aus")

    def __init__(self, backoff: Backoff, *, auto_retry: bool = True,
                 clock: Callable[[], float] = time.monotonic):
        self._backoff = backoff
        self._auto_retry = auto_retry
        self._clock = clock
        self._fails = 0
        self._manual = False
        self._ready_at = clock()

    @property
    def auto_retry(self) -> bool:
        return self._auto_retry

    def configure(self, *, backoff: Backoff | None = None, auto_retry: bool | None = None) -> None:
        """Neue Einstellungen ohne Neustart (reload). Ein kürzerer Backoff verkürzt die laufende Wartezeit."""
        if backoff is not None:
            self._backoff = backoff
            if self._fails > 0:
                self._ready_at = min(self._ready_at, self._clock() + backoff.delay(self._fails))
        if auto_retry is not None:
            self._auto_retry = bool(auto_retry)

    def on_offline(self) -> float:
        self._fails += 1
        delay = self._backoff.delay(self._fails)
        self._ready_at = self._clock() + delay
        return delay

    def on_online(self) -> None:
        self._fails = 0
        self._ready_at = self._clock()

    def on_manual_retry(self) -> None:
        self._manual = True
        self._ready_at = self._clock()

    def ready(self) -> bool:
        if self._clock() < self._ready_at:
            return False
        return self._auto_retry or self._manual

    def decide(self, has_due_jobs: bool, probe_result: bool | None) -> RetryDecision:
        if not has_due_jobs:
            return RetryDecision("warten", self.NO_JOBS_WAIT_S, "")
        if not self._auto_retry and not self._manual:
            return RetryDecision("warten", self.AUTO_OFF_WAIT_S, _t(self.AUTO_OFF_REASON))
        now = self._clock()
        if now < self._ready_at:
            rest = self._ready_at - now
            return RetryDecision("warten", rest,
                                  _t("Warte auf nächsten Versuch in {rest} s", rest=int(round(rest))))
        self._manual = False  # einmalig verbraucht
        if probe_result is False:
            wait = self.on_offline()
            return RetryDecision(
                "warten", wait,
                _t("Drucker nicht erreichbar (BLE), nächster Versuch in {wait} s", wait=int(round(wait))))
        return RetryDecision("drucken", 0.0, "")

    @property
    def next_try_in(self) -> float | None:
        rest = self._ready_at - self._clock()
        return rest if rest > 0 else None
