"""Begrenzung der Fehlversuche je Client-Adresse.

Höchstens `max_failures` falsche Tokens innerhalb von `window_s`, danach `lockout_s` Sperre.
Thread-sicher, Speicher auf `max_entries` Adressen begrenzt (älteste fliegen zuerst raus),
abgelaufene Einträge werden bei jedem Fehlversuch aufgeräumt.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class _Entry:
    failures: deque = field(default_factory=deque)
    locked_until: float = 0.0


class FailureLimiter:
    def __init__(self, *, max_failures: int = 10, window_s: float = 600.0, lockout_s: float = 900.0,
                 clock: Callable[[], float] = time.monotonic, max_entries: int = 4096):
        self.max_failures = int(max_failures)
        self.window_s = float(window_s)
        self.lockout_s = float(lockout_s)
        self.max_entries = int(max_entries)
        self._clock = clock
        self._lock = threading.Lock()
        self._entries: OrderedDict[str, _Entry] = OrderedDict()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def tracked(self) -> list[str]:
        """Adressen mit Einträgen, älteste zuerst (für Tests und Diagnose)."""
        with self._lock:
            return list(self._entries)

    def _expired(self, entry: _Entry, now: float) -> bool:
        if entry.locked_until > now:
            return False
        if entry.locked_until:
            return True                      # Sperre abgelaufen: Zählung beginnt neu
        while entry.failures and entry.failures[0] <= now - self.window_s:
            entry.failures.popleft()
        return not entry.failures

    def _cleanup(self, now: float) -> None:
        for key in [k for k, e in self._entries.items() if self._expired(e, now)]:
            del self._entries[key]

    def blocked(self, client: str) -> float:
        """Verbleibende Sperrsekunden, 0.0 wenn frei."""
        now = self._clock()
        with self._lock:
            entry = self._entries.get(client)
            if entry is None:
                return 0.0
            remaining = entry.locked_until - now
            if remaining > 0:
                return remaining
            if entry.locked_until:
                del self._entries[client]
            return 0.0

    def failure(self, client: str) -> None:
        now = self._clock()
        with self._lock:
            self._cleanup(now)
            entry = self._entries.get(client)
            if entry is None:
                entry = _Entry()
                self._entries[client] = entry
            if entry.locked_until > now:
                return
            while entry.failures and entry.failures[0] <= now - self.window_s:
                entry.failures.popleft()
            entry.failures.append(now)
            if len(entry.failures) >= self.max_failures:
                entry.failures.clear()
                entry.locked_until = now + self.lockout_s
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)

    def success(self, client: str) -> None:
        with self._lock:
            entry = self._entries.get(client)
            if entry is not None and entry.locked_until <= self._clock():
                del self._entries[client]
