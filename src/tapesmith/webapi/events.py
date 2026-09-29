"""Ereignisverteilung an SSE-Abonnenten: Zustand, Status, Fortschritt, Aufträge.

`EventBroker.publish` ist thread-sicher und blockiert nie. Jeder Abonnent hat eine eigene,
begrenzte Queue; ist sie voll, fällt das älteste Ereignis weg (ein langsamer Browser bremst den
Druck nie).
"""

from __future__ import annotations

import json
import queue
import threading

Event = tuple[str, dict]

_CLOSE = object()


def sse_format(event: str, data: dict) -> str:
    """Ein SSE-Ereignis: `event: <name>`, eine Datenzeile mit kompaktem JSON, Leerzeile."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


class Subscription:
    def __init__(self, broker: EventBroker, maxsize: int):
        self._broker = broker
        self._queue: queue.Queue = queue.Queue(maxsize=max(1, int(maxsize)))
        self._lock = threading.Lock()
        self.closed = False

    def _put(self, item) -> None:
        with self._lock:
            if self.closed:
                return
            while True:
                try:
                    self._queue.put_nowait(item)
                    return
                except queue.Full:
                    try:
                        self._queue.get_nowait()
                    except queue.Empty:
                        pass

    def get(self, timeout: float) -> Event | None:
        """Nächstes Ereignis oder None (Zeitablauf oder Abo beendet)."""
        if self.closed:
            return None
        try:
            item = self._queue.get(timeout=timeout)
        except queue.Empty:
            return None
        if item is _CLOSE or self.closed:
            return None
        return item

    def _shutdown(self) -> None:
        with self._lock:
            if self.closed:
                return
            self.closed = True
            while True:
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    break
            self._queue.put_nowait(_CLOSE)   # weckt einen wartenden get()

    def close(self) -> None:
        self._broker._remove(self)
        self._shutdown()


class EventBroker:
    def __init__(self):
        self._lock = threading.Lock()
        self._subs: list[Subscription] = []

    def publish(self, event: str, data: dict) -> None:
        with self._lock:
            subs = list(self._subs)
        item = (event, dict(data))
        for sub in subs:
            sub._put(item)

    def subscribe(self, maxsize: int = 256) -> Subscription:
        sub = Subscription(self, maxsize)
        with self._lock:
            self._subs.append(sub)
        return sub

    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subs)

    def _remove(self, sub: Subscription) -> None:
        with self._lock:
            if sub in self._subs:
                self._subs.remove(sub)

    def close_all(self) -> None:
        with self._lock:
            subs, self._subs = self._subs, []
        for sub in subs:
            sub._shutdown()
