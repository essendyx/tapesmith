"""Client des Druckdienstes p12d: Verbindung + Handshake, thread-sichere Anfragen, Ereignisse.

Ein Lese-Thread empfängt alle Nachrichten: Antworten werden per `id` der wartenden Anfrage
zugeordnet, Ereignisse an die Listener verteilt (im Lese-Thread; Listener müssen schnell sein
und dürfen nicht selbst `call` blockierend auf den Lese-Thread warten lassen). Bricht der Kanal
ab, enden alle wartenden Anfragen mit `DaemonLost`.
"""

from __future__ import annotations

import itertools
import logging
import threading
from collections.abc import Callable

from tapesmith.ipc import pipe
from tapesmith.ipc.codec import decode_error
from tapesmith.ipc.pipe import Channel, ChannelClosed, client_handshake, home_key, pipe_name
from tapesmith.ipc.protocol import IpcError, request
from tapesmith.i18n import N_, _t

log = logging.getLogger(__name__)

LOST_TEXT = N_("Verbindung zum Druckdienst verloren, Ergebnis im Verlauf prüfen")
NOT_SENT_TEXT = N_("Keine Verbindung zum Druckdienst (Anfrage nicht gesendet)")


class DaemonLost(IpcError):
    """Verbindung zum Druckdienst während einer Anfrage verloren (Exit 5)."""

    def __init__(self, message: str | None = None):
        super().__init__(_t(LOST_TEXT) if message is None else message)


class DaemonNotSent(DaemonLost):
    """Kanal war schon zu, bevor die Anfrage raus ging: der Dienst hat sie sicher nicht erhalten.

    Nur in diesem Fall darf ein Aufrufer neu verbinden und die Anfrage wiederholen."""

    def __init__(self, message: str | None = None):
        super().__init__(_t(NOT_SENT_TEXT) if message is None else message)


class _Pending:
    __slots__ = ("done", "msg", "lost")

    def __init__(self) -> None:
        self.done = threading.Event()
        self.msg: dict | None = None
        self.lost = False


class DaemonClient:
    def __init__(self, channel: Channel, welcome: dict):
        self._channel = channel
        self._welcome = dict(welcome)
        self._ids = itertools.count(1)
        self._lock = threading.Lock()
        self._pending: dict[int, _Pending] = {}
        self._listeners: dict[str, list[Callable[[dict], None]]] = {}
        self._closed = False
        self._reader = threading.Thread(target=self._read_loop, name="p12-daemon-client", daemon=True)
        self._reader.start()

    @classmethod
    def connect(cls, *, client: str, name: str | None = None, timeout_s: float = 2.0,
                home: str | None = None,
                connector: Callable[[str, float], Channel] = pipe.connect) -> "DaemonClient":
        channel = connector(name or pipe_name(), timeout_s)
        try:
            welcome = client_handshake(channel, client, home=home or home_key(), timeout_s=timeout_s)
        except BaseException:
            try:
                channel.close()
            except Exception:  # noqa: BLE001
                pass
            raise
        return cls(channel, welcome)

    # ---------- Eigenschaften ----------

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def server_pid(self) -> int:
        return int(self._welcome.get("pid", 0))

    @property
    def server_version(self) -> str:
        return str(self._welcome.get("version", ""))

    # ---------- Anfragen ----------

    def call(self, method: str, params: dict | None = None, *, timeout: float | None = 30.0) -> dict:
        with self._lock:
            if self._closed:
                raise DaemonNotSent()
            msg_id = next(self._ids)
            pending = _Pending()
            self._pending[msg_id] = pending
        try:
            self._channel.send(request(msg_id, method, params))
        except ChannelClosed as exc:
            with self._lock:
                self._pending.pop(msg_id, None)
            raise DaemonNotSent() from exc
        except BaseException:
            with self._lock:
                self._pending.pop(msg_id, None)
            raise
        if not pending.done.wait(timeout):
            with self._lock:
                self._pending.pop(msg_id, None)
            if not pending.done.is_set():
                raise IpcError(_t("Druckdienst antwortet nicht ({method})", method=method))
        if pending.lost or pending.msg is None:
            raise DaemonLost()
        msg = pending.msg
        if msg["ok"]:
            return msg["result"]
        raise decode_error(msg["error"])

    # ---------- Ereignisse ----------

    def add_listener(self, event: str, callback: Callable[[dict], None]) -> None:
        """`event` "*" = alle Ereignisse; diese Listener bekommen `{"event": name, "data": data}`."""
        with self._lock:
            self._listeners.setdefault(event, []).append(callback)

    def remove_listener(self, event: str, callback) -> None:
        with self._lock:
            callbacks = self._listeners.get(event, [])
            try:
                callbacks.remove(callback)
            except ValueError:
                pass

    def _dispatch(self, name: str, data: dict) -> None:
        with self._lock:
            named = list(self._listeners.get(name, ()))
            wildcard = list(self._listeners.get("*", ()))
        for callback in named:
            try:
                callback(data)
            except Exception:  # noqa: BLE001 (ein Listener darf den Lese-Thread nicht beenden)
                log.exception("Fehler im Listener für '%s'", name)
        for callback in wildcard:
            try:
                callback({"event": name, "data": data})
            except Exception:  # noqa: BLE001
                log.exception("Fehler im Listener für '*'")

    # ---------- Lese-Thread ----------

    def _read_loop(self) -> None:
        try:
            while True:
                try:
                    msg = self._channel.recv(timeout=None)
                except IpcError:
                    break
                if msg is None:
                    continue
                kind = msg.get("type")
                if kind == "response":
                    with self._lock:
                        pending = self._pending.pop(msg.get("id"), None)
                    if pending is not None and "ok" in msg:
                        pending.msg = msg
                        pending.done.set()
                elif kind == "event" and isinstance(msg.get("data"), dict):
                    self._dispatch(str(msg.get("event")), msg["data"])
        finally:
            self._shutdown()

    def _shutdown(self) -> None:
        with self._lock:
            self._closed = True
            pending = list(self._pending.values())
            self._pending.clear()
        for item in pending:
            item.lost = True
            item.done.set()
        try:
            self._channel.close()
        except Exception:  # noqa: BLE001
            pass

    def close(self) -> None:
        with self._lock:
            self._closed = True
        try:
            self._channel.close()
        except Exception:  # noqa: BLE001
            pass
        if threading.current_thread() is not self._reader:
            self._reader.join(2)

    def __enter__(self) -> "DaemonClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
