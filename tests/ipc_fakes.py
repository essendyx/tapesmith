"""Test-Hilfen für IPC-Clients: Fake-Druckdienst auf der Server-Seite von `memory_channel_pair()`.

Kein Prozess, keine Pipe: der Fake läuft in Threads im Testprozess (je Verbindung ein eigenes
Kanalpaar, wie beim echten Pipe-Server), beantwortet `hello` mit
`welcome` (oder einem Handshake-Fehler), verteilt Anfragen an eine Methode→Handler-Tabelle und
kann Ereignisse senden. Jeder Handler läuft in einem eigenen Thread, damit ein verzögerter
Handler andere Anfragen nicht aufhält.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from tapesmith.ipc import codec, protocol
from tapesmith.ipc.pipe import ChannelClosed, memory_channel_pair

HOME = "testhome"

Handler = Callable[["FakeServer", dict], dict]


class FakeServer:
    def __init__(self, handlers: dict[str, Handler] | None = None, *, pid: int = 4711,
                 version: str = "9.9", home: str = HOME, handshake_error: dict | None = None):
        self.handlers: dict[str, Handler] = dict(handlers or {})
        self.welcome = protocol.welcome(home, pid=pid, version=version)
        self.handshake_error = handshake_error
        self.requests: list[tuple[str, dict]] = []
        self.hellos: list[dict] = []
        self._lock = threading.Lock()
        self._channels: list = []
        self._closed = False

    # ---------- Test-Seite ----------

    def calls(self, method: str) -> list[dict]:
        with self._lock:
            return [params for m, params in self.requests if m == method]

    def methods(self) -> list[str]:
        with self._lock:
            return [m for m, _p in self.requests]

    def emit(self, name: str, data: dict | None = None) -> None:
        with self._lock:
            channels = [ch for ch in self._channels if not ch.closed]
        for channel in channels:
            self._send(channel, protocol.event(name, data))

    def close(self) -> None:
        with self._lock:
            self._closed = True
            channels = list(self._channels)
        for channel in channels:
            channel.close()

    def open_channel(self):
        """Neue Verbindung: Client-Seite zurück, Server-Seite läuft in einem eigenen Thread."""
        client_side, server_side = memory_channel_pair()
        with self._lock:
            self._channels.append(server_side)
            closed = self._closed
        if closed:
            server_side.close()
        threading.Thread(target=self._loop, args=(server_side,), name="fake-p12d", daemon=True).start()
        return client_side

    def connector(self, name: str, timeout_s: float):
        return self.open_channel()

    def client(self):
        from tapesmith.ipc.client import DaemonClient

        return DaemonClient(self.open_channel(), self.welcome)

    # ---------- Server-Schleife ----------

    def _loop(self, channel) -> None:
        while True:
            try:
                msg = channel.recv(timeout=None)
            except ChannelClosed:
                return
            if msg is None:
                continue
            if msg["type"] == "hello":
                with self._lock:
                    self.hellos.append(msg)
                if self.handshake_error is not None:
                    self._send(channel, self.handshake_error)
                    channel.close()
                    return
                self._send(channel, self.welcome)
            elif msg["type"] == "request":
                with self._lock:
                    self.requests.append((msg["method"], msg["params"]))
                threading.Thread(target=self._handle, args=(channel, msg), daemon=True).start()

    def _handle(self, channel, msg: dict) -> None:
        handler = self.handlers.get(msg["method"])
        try:
            if handler is None:
                result = {}
            else:
                result = handler(self, msg["params"])
        except Exception as exc:  # noqa: BLE001 (wird als Fehlerantwort gesendet)
            self._send(channel, protocol.response_error(msg["id"], codec.encode_error(exc)))
            return
        if result is NO_REPLY:
            return
        self._send(channel, protocol.response_ok(msg["id"], result))

    def _send(self, channel, msg: dict) -> None:
        try:
            channel.send(msg)
        except ChannelClosed:
            pass


NO_REPLY = object()


def ok_outcome(**kw) -> dict:
    data = {"status": "ok", "warnings": [], "reasons": [], "history_id": 42, "consumed_mm": 12.0,
            "results": [{"rows": 80, "rows_sent": 80, "waited_s": 0.1, "status": "ok"}],
            "printer_status": None, "error": None, "queue_id": None}
    data.update(kw)
    return data


def daemon_handlers() -> dict[str, Handler]:
    """Minimale Antworten eines gesunden Dienstes (Zustand, Status, Warteschlange, Druck)."""
    state = {"state": "getrennt", "transport": None, "last_error": None, "leased": False}
    return {
        "state": lambda s, p: dict(state),
        "status": lambda s, p: {"state": dict(state), "status": None, "checked_at": None},
        "queue.list": lambda s, p: {"jobs": [], "paused": False, "auto_retry": True, "next_try": None,
                                    "probe": "", "waiting_reason": ""},
        "print": lambda s, p: ok_outcome(),
    }


class RestartableDaemon:
    """Fake-Dienst, der beendet und neu gestartet werden kann (neuer FakeServer, neue PID).

    `connector` hat die Signatur von `DaemonClient.connect`; bei gestopptem Dienst wirft er
    `DaemonUnavailable` wie die echte Pipe."""

    def __init__(self, handlers_factory: Callable[[], dict[str, Handler]] = daemon_handlers):
        self._handlers_factory = handlers_factory
        self.servers: list[FakeServer] = []
        self.current: FakeServer | None = None
        self.connects = 0
        self.start()

    def start(self) -> FakeServer:
        self.current = FakeServer(self._handlers_factory(), pid=4711 + len(self.servers))
        self.servers.append(self.current)
        return self.current

    def stop(self) -> None:
        if self.current is not None:
            self.current.close()
            self.current = None

    def restart(self) -> FakeServer:
        self.stop()
        return self.start()

    def connector(self, *, client: str = "test", timeout_s: float = 2.0, **_kw):
        from tapesmith.ipc.pipe import DaemonUnavailable

        self.connects += 1
        if self.current is None:
            raise DaemonUnavailable("Druckdienst läuft nicht")
        return self.current.client()

    def close(self) -> None:
        for server in self.servers:
            server.close()
