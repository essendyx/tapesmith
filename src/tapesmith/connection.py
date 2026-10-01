"""Verbindungsmanager: Verbindung bei Bedarf, Vorverbinden, Trennen im Leerlauf,
schnelle Offline-Erkennung.

Ein einziger Worker-Thread besitzt Drucksperre und Transport: Der Windows-Named-Mutex hinter
`PrintLock` ist threadgebunden (nur der besitzende Thread darf `ReleaseMutex` rufen). Deshalb
öffnet, druckt, trennt und entsperrt ausschließlich dieser Thread; alle Aufrufe werden als
Aufträge in seine Queue gestellt. Aufrufer warten mit hartem Timeout auf den Verbindungsaufbau
und frieren so nie ein.
"""

from __future__ import annotations

import queue
import threading
import time
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeout
from enum import Enum
from typing import Any, Callable, TypeVar

from tapesmith.device.profile import DeviceProfile
from tapesmith.lock import PrinterBusy, PrintLock
from tapesmith.printer import PrinterSession
from tapesmith.transport.base import ConnectTimeout, Transport, TransportError
from tapesmith.i18n import _t

T = TypeVar("T")

_POLL_S = 0.01


class ConnectionState(str, Enum):
    DISCONNECTED = "getrennt"
    CONNECTING = "verbindet"
    CONNECTED = "verbunden"
    OFFLINE = "offline"       # letzter Versuch per Timeout gescheitert (Backoff läuft)
    BUSY = "belegt"           # PrinterBusy beim Sperren
    ERROR = "fehler"          # sonstiger Fehler beim Verbinden


class PrinterOffline(ConnectTimeout):
    """Drucker nicht erreichbar (CLI: Exit-Code 5)."""


class _NullLock:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _HeldTransport:
    """Hülle um den gehaltenen Transport: open/close sind No-ops, der Manager verwaltet ihn."""

    def __init__(self, inner: Transport):
        self._inner = inner
        self.name = inner.name

    def open(self) -> None:
        pass

    def close(self) -> None:
        pass

    def write(self, data: bytes) -> None:
        self._inner.write(data)

    def read(self, timeout: float) -> bytes:
        return self._inner.read(timeout)

    def __getattr__(self, attr):  # z. B. supports_responses
        return getattr(self._inner, attr)


_STOP = object()


class ConnectionManager:
    def __init__(self, transport_factory: Callable[[], Transport], profile: DeviceProfile, *,
                 idle_timeout_s: float = 300.0, connect_timeout_s: float = 5.0,
                 offline_backoff_s: float = 10.0, lock_factory: Callable[[], Any] = PrintLock,
                 session_factory: Callable[..., PrinterSession] = PrinterSession,
                 sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic,
                 on_state: Callable[[ConnectionState], None] | None = None):
        self._factory = transport_factory
        self._profile = profile
        self._idle_timeout_s = idle_timeout_s
        self._connect_timeout_s = connect_timeout_s
        self._offline_backoff_s = offline_backoff_s
        self._lock_factory = lock_factory
        self._session_factory = session_factory
        self._sleep = sleep
        self._clock = clock
        self._on_state = on_state

        self._mutex = threading.Lock()
        self._queue: queue.Queue = queue.Queue()
        self._worker: threading.Thread | None = None
        self._closed = False
        self._state = ConnectionState.DISCONNECTED
        self._notified = ConnectionState.DISCONNECTED   # zuletzt an on_state gemeldet (nur Worker)
        self._last_error: BaseException | None = None
        self._offline_until = 0.0
        self._offline_checked_at = 0.0
        self._last_activity = 0.0
        self._in_job = False           # Worker führt gerade fn aus (zählt nicht zum Timeout)
        # nur im Worker-Thread benutzt:
        self._transport: Transport | None = None
        self._lock: Any = None
        self._transport_name: str | None = None   # vom Worker gesetzt, von allen lesbar

    # ---------- öffentliche Schnittstelle ----------

    @property
    def state(self) -> ConnectionState:
        return self._state

    @property
    def last_error(self) -> BaseException | None:
        return self._last_error

    @property
    def transport_name(self) -> str | None:
        """Name des aktuell gehaltenen Transports (z. B. "COM4", "ble:A4:…"), sonst None."""
        return self._transport_name

    def set_profile(self, profile: DeviceProfile) -> None:
        """Neues Geräteprofil; gilt ab der nächsten Sitzung (laufende Aufträge behalten ihres)."""
        with self._mutex:
            self._profile = profile

    def preconnect(self) -> None:
        """Verbindung im Hintergrund aufbauen, ohne zu blockieren."""
        with self._mutex:
            if self._closed or self._backoff_active() or self._state in (
                    ConnectionState.CONNECTING, ConnectionState.CONNECTED):
                return
        threading.Thread(target=self._preconnect_bg, name="P12-Vorverbinden", daemon=True).start()

    def connect(self, timeout: float | None = None, force: bool = False,
                factory: Callable[[], Transport] | None = None) -> None:
        """Verbindung aufbauen. `factory` ersetzt für diesen einen Aufbau die Transport-Fabrik
        (z. B. mit längerer Wartezeit für „Erneut verbinden“)."""
        if not force:
            self._raise_if_backoff()
        started = Future()
        connected = Future()
        self._submit(lambda: self._job_connect(started, connected, factory))
        self._await_connect(started, connected, timeout, job=None)

    def run(self, fn: Callable[[PrinterSession], T], timeout: float | None = None) -> T:
        self._raise_if_backoff()
        started: Future = Future()
        connected: Future = Future()
        result: Future = Future()
        self._submit(lambda: self._job_run(fn, started, connected, result))
        self._await_connect(started, connected, timeout, job=result)
        return result.result()

    def disconnect(self) -> None:
        with self._mutex:
            worker = self._worker
        if worker is None or not worker.is_alive():
            return
        done: Future = Future()
        self._submit(lambda: self._job_disconnect(done))
        done.result()

    def close(self) -> None:
        with self._mutex:
            if self._closed:
                return
            self._closed = True
            worker = self._worker
        if worker is not None and worker.is_alive():
            self._queue.put(_STOP)
            worker.join(timeout=2)

    def __enter__(self) -> "ConnectionManager":
        return self

    def __exit__(self, *exc) -> bool:
        self.close()
        return False

    # ---------- Aufrufer-Seite ----------

    def _backoff_active(self) -> bool:
        return self._offline_until > self._clock()

    def _raise_if_backoff(self) -> None:
        with self._mutex:
            if not self._backoff_active():
                return
            ago = self._clock() - self._offline_checked_at
        raise PrinterOffline(_t("Drucker offline (zuletzt vor {ago:.0f} s geprüft)", ago=ago))

    def _preconnect_bg(self) -> None:
        try:
            self.connect()
        except Exception:
            pass  # Zustand/last_error sind gesetzt; Vorverbinden meldet nichts

    def _submit(self, job: Callable[[], None]) -> None:
        with self._mutex:
            if self._closed:
                raise TransportError(_t("Verbindungsmanager geschlossen"))
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(target=self._loop, name=_t("P12-Verbindung"), daemon=True)
                self._worker.start()
        self._queue.put(job)

    def _await_connect(self, started: Future, connected: Future, timeout: float | None,
                       job: Future | None) -> None:
        """Wartet auf den Verbindungsteil. Zeit, in der der Worker einen anderen Auftrag (fn)
        ausführt, zählt nicht zum Timeout, nur Warten auf den Aufbau selbst."""
        limit = timeout or self._connect_timeout_s
        waited = 0.0
        last = time.monotonic()
        while True:
            try:
                connected.result(timeout=min(_POLL_S, max(limit - waited, 0.0)))
                return
            except FutureTimeout:
                pass
            now = time.monotonic()
            if started.done() or not self._in_job:
                waited += now - last
            last = now
            if waited >= limit:
                break
        # Zeit abgelaufen: Auftrag zurückziehen, damit fn nicht später unerwartet noch druckt
        if job is not None and not job.cancel():
            return  # Verbindung stand gerade noch, fn läuft bereits bzw. ist fertig
        if job is None and connected.done():
            connected.result()  # gerade noch fertig geworden: Erfolg oder dessen Fehler
            return
        started.cancel()
        err = PrinterOffline(_t("Drucker nicht erreichbar (keine Antwort nach {limit:.0f} s). Eingeschaltet und in Reichweite? Handy-App getrennt?", limit=limit))
        with self._mutex:
            if self._transport is None:
                now = self._clock()
                self._offline_until = now + self._offline_backoff_s
                self._offline_checked_at = now
                self._last_error = err
                self._state = ConnectionState.OFFLINE
        # on_state meldet ausschließlich der Worker: sobald er frei ist (ggf. erst nach dem
        # hängenden open()), holt er die Meldung nach.
        try:
            self._submit(self._job_report_state)
        except TransportError:
            pass
        raise err

    # ---------- Worker-Seite ----------

    def _set_state(self, state: ConnectionState, error: BaseException | None = None) -> None:
        with self._mutex:
            pending = self._state      # evtl. vom Aufrufer gesetzt (OFFLINE nach Timeout)
            self._state = state
            if error is not None:
                self._last_error = error
        self._report(pending)          # noch nicht gemeldeten Zwischenzustand nachholen
        self._report(state)

    def _report(self, state: ConnectionState) -> None:
        """Meldet einen Zustand an on_state, falls noch nicht gemeldet. Nur im Worker rufen."""
        if state is self._notified:
            return
        self._notified = state
        self._notify(state)

    def _job_report_state(self) -> None:
        with self._mutex:
            state = self._state
        self._report(state)

    def _notify(self, state: ConnectionState) -> None:
        if self._on_state is None:
            return
        try:
            self._on_state(state)
        except Exception:
            pass

    def _loop(self) -> None:
        while True:
            wait = None
            if self._transport is not None and self._idle_timeout_s > 0:
                wait = self._last_activity + self._idle_timeout_s - self._clock()
                if wait <= 0:
                    self._drop()
                    continue
            try:
                job = self._queue.get(timeout=wait)
            except queue.Empty:
                continue
            if job is _STOP:
                self._drop()
                return
            try:
                job()
            except BaseException:  # pragma: no cover (Aufträge setzen ihre Futures selbst)
                pass

    def _ensure_connected(self, factory: Callable[[], Transport] | None = None) -> None:
        if self._transport is not None:
            return
        self._set_state(ConnectionState.CONNECTING)
        try:
            lock = self._lock_factory()
            lock.__enter__()
        except PrinterBusy as exc:
            self._set_state(ConnectionState.BUSY, exc)
            raise
        except BaseException as exc:
            self._set_state(ConnectionState.ERROR, exc)
            raise
        try:
            transport = (factory or self._factory)()
            transport.open()
        except BaseException as exc:
            try:
                lock.__exit__(None, None, None)
            finally:
                if isinstance(exc, ConnectTimeout):
                    with self._mutex:
                        now = self._clock()
                        self._offline_until = now + self._offline_backoff_s
                        self._offline_checked_at = now
                    self._set_state(ConnectionState.OFFLINE, exc)
                else:
                    self._set_state(ConnectionState.ERROR, exc)
            raise
        with self._mutex:
            self._transport = transport
            self._lock = lock
            self._transport_name = getattr(transport, "name", None)
            self._offline_until = 0.0
            self._last_activity = self._clock()
        self._set_state(ConnectionState.CONNECTED)

    def _drop(self) -> None:
        transport, lock = self._transport, self._lock
        if transport is None:
            return
        with self._mutex:
            self._transport = None
            self._lock = None
            self._transport_name = None
        try:
            transport.close()
        except Exception:
            pass
        finally:
            try:
                lock.__exit__(None, None, None)
            except Exception:
                pass
            self._set_state(ConnectionState.DISCONNECTED)

    def _job_connect(self, started: Future, connected: Future,
                     factory: Callable[[], Transport] | None = None) -> None:
        if not started.set_running_or_notify_cancel():
            return
        try:
            self._ensure_connected(factory)
        except BaseException as exc:
            started.set_result(None)
            connected.set_exception(exc)
            return
        started.set_result(None)
        connected.set_result(None)

    def _job_run(self, fn: Callable[[PrinterSession], Any], started: Future, connected: Future,
                 result: Future) -> None:
        self._job_connect(started, connected)
        if not connected.done() or connected.exception() is not None:
            result.cancel()
            return
        if not result.set_running_or_notify_cancel():
            return
        self._in_job = True
        try:
            with self._mutex:
                profile = self._profile
            session = self._session_factory(_HeldTransport(self._transport), profile,
                                            lock=_NullLock(), sleep=self._sleep)
            value = fn(session)
        except BaseException as exc:
            if isinstance(exc, TransportError):
                self._drop()
            result.set_exception(exc)
        else:
            result.set_result(value)
        finally:
            self._in_job = False
            self._last_activity = self._clock()
            if self._idle_timeout_s == 0:
                self._drop()

    def _job_disconnect(self, done: Future) -> None:
        try:
            self._drop()
        finally:
            done.set_result(None)
