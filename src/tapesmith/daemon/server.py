"""Named-Pipe-Server des Druckdienstes (Protokoll v1): Anfragen an den `PrintService`,
Ereignisse an alle verbundenen Clients.

Langlaufende Methoden (`print`, `status` mit `fresh`, `lease`) laufen in eigenen Threads, damit
dieselbe Verbindung währenddessen `cancel`/`continue_cut` senden kann. Schließt ein Client, werden
seine Reservierungen freigegeben.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable

import tapesmith
from tapesmith.ipc import protocol
from tapesmith.ipc.codec import decode_request, encode_error, encode_outcome, encode_report, encode_state
from tapesmith.ipc.pipe import Channel, ChannelClosed, PipeServer, home_key, pipe_name, server_handshake
from tapesmith.ipc.protocol import IpcError, ProtocolError

from tapesmith.daemon.service import PrintService
from tapesmith import i18n
from tapesmith.i18n import _t

log = logging.getLogger(__name__)


def _params(msg: dict) -> dict:
    params = msg.get("params")
    return params if isinstance(params, dict) else {}


def _required(params: dict, name: str):
    if name not in params:
        raise ProtocolError(_t("Parameter '{name}' fehlt", name=name))
    return params[name]


def _int(params: dict, name: str) -> int:
    value = _required(params, name)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ProtocolError(_t("Parameter '{name}' muss eine Zahl sein", name=name))
    return value


class DaemonServer:
    def __init__(self, service: PrintService, *, name: str | None = None, home: str | None = None,
                 on_shutdown: Callable[[], None] | None = None):
        self._service = service
        self._name = name or pipe_name()
        self._home = home or home_key()
        self._on_shutdown = on_shutdown
        self._lock = threading.Lock()
        self._channels: set = set()
        self._pipe: PipeServer | None = None
        self._started_at = time.monotonic()
        service.set_emitter(self.broadcast)

    # ---------- Lebenszyklus ----------

    @property
    def name(self) -> str:
        return self._name

    def start(self) -> None:
        pipe = PipeServer(self._name, self._handle)
        pipe.start()   # PipeInUse wird weitergereicht
        self._pipe = pipe
        self._started_at = time.monotonic()
        log.info("Pipe-Server gestartet: %s", self._name)

    def stop(self) -> None:
        pipe, self._pipe = self._pipe, None
        if pipe is not None:
            pipe.stop()
        with self._lock:
            channels = list(self._channels)
            self._channels.clear()
        for channel in channels:
            try:
                channel.close()
            except Exception:  # noqa: BLE001
                pass

    @property
    def clients(self) -> int:
        with self._lock:
            return sum(1 for ch in self._channels if not ch.closed)

    # ---------- Ereignisse ----------

    def broadcast(self, event: str, data: dict) -> None:
        try:
            msg = protocol.event(event, data)
        except ProtocolError:
            log.exception("Unbekanntes Ereignis %s", event)
            return
        with self._lock:
            channels = list(self._channels)
        for channel in channels:
            try:
                channel.send(msg)
            except Exception:  # noqa: BLE001 (Sendefehler -> Kanal schließen)
                self._drop(channel)

    def _drop(self, channel: Channel) -> None:
        with self._lock:
            self._channels.discard(channel)
        try:
            channel.close()
        except Exception:  # noqa: BLE001
            pass

    # ---------- Verbindungen ----------

    _THREADED = frozenset({"print", "lease"})

    def _threaded(self, msg: dict) -> bool:
        method = msg.get("method")
        if method in self._THREADED:
            return True
        return method == "status" and bool(_params(msg).get("fresh", True))

    def _handle(self, channel: Channel) -> None:
        try:
            server_handshake(channel, home=self._home)
        except IpcError as exc:
            log.info("Handshake abgelehnt: %s", exc)
            return
        with self._lock:
            self._channels.add(channel)
        try:
            while True:
                msg = channel.recv()
                if msg is None:
                    continue
                if msg.get("type") == "request" and self._threaded(msg):
                    threading.Thread(target=self._answer, args=(channel, msg), daemon=True,
                                     name=f"p12d-{msg.get('method')}").start()
                else:
                    self._answer(channel, msg)
        except ChannelClosed:
            pass
        except ProtocolError as exc:
            log.info("Verbindung wegen Protokollfehler getrennt: %s", exc)
        finally:
            with self._lock:
                self._channels.discard(channel)
            try:
                self._service.release_owner(channel)
            except Exception:  # noqa: BLE001
                log.exception("Reservierung nicht freigegeben")

    def _answer(self, channel: Channel, msg: dict) -> None:
        response = self.dispatch(channel, msg)
        if msg.get("method") == "lease" and channel.closed:
            # Client ging, während die Reservierung noch auf die Sperre wartete.
            self._service.release_owner(channel)
        if response is None:
            return
        try:
            channel.send(response)
        except IpcError:
            pass

    # ---------- Anfragen ----------

    def dispatch(self, channel: Channel, msg: dict) -> dict | None:
        # Meldungen in der Sprache des Clients (optionales Feld `lang`, ältere Clients senden keins).
        with i18n.use_language(msg.get("lang") if isinstance(msg.get("lang"), str) else None):
            return self._dispatch(channel, msg)

    def _dispatch(self, channel: Channel, msg: dict) -> dict | None:
        msg_id = msg.get("id") if isinstance(msg.get("id"), int) else 0
        try:
            protocol.check_message(msg)
            if msg["type"] != "request":
                raise ProtocolError(_t("Anfrage erwartet, '{type}' erhalten", type=msg['type']))
            result = self._call(channel, msg["method"], msg["params"])
        except Exception as exc:  # noqa: BLE001 (jeder Fehler wird zur Fehlerantwort)
            if not isinstance(exc, (ProtocolError, IpcError)):
                log.info("Anfrage %s fehlgeschlagen: %s: %s", msg.get("method"), type(exc).__name__, exc)
            return protocol.response_error(msg_id, encode_error(exc))
        return protocol.response_ok(msg_id, result)

    def _call(self, channel: Channel, method: str, params: dict) -> dict:
        service = self._service
        if method == "ping":
            return {"pid": os.getpid(), "uptime_s": round(time.monotonic() - self._started_at, 3),
                    "clients": self.clients, "version": tapesmith.__version__}
        if method == "print":
            request = decode_request(_required(params, "request"))
            outcome = service.submit(request, job_key=str(_required(params, "job_key")),
                                     enqueue_on_offline=bool(params.get("enqueue_on_offline", False)))
            return encode_outcome(outcome)
        if method == "cancel":
            return {"cancelled": service.cancel(str(_required(params, "job_key")))}
        if method == "continue_cut":
            return {"was_pausing": service.continue_cut()}
        if method == "preconnect":
            service.preconnect()
            return {}
        if method == "disconnect":
            service.disconnect()
            return {}
        if method == "state":
            return encode_state(service.state())
        if method == "status":
            report = service.status(quick=bool(params.get("quick", False)), fresh=bool(params.get("fresh", True)))
            return encode_report(report)
        if method == "lease":
            timeout_s = float(params.get("timeout_s", 120.0))
            return {"lease_id": service.lease(channel, timeout_s)}
        if method == "release":
            service.release(str(_required(params, "lease_id")))
            return {}
        if method == "reload":
            return {"profile": service.reload().model}
        if method == "queue.list":
            return service.queue_snapshot(bool(params.get("include_done", False)))
        if method == "queue.cancel":
            return {"ok": service.queue_cancel(_int(params, "id"))}
        if method == "queue.duplicate":
            return {"id": service.queue_duplicate(_int(params, "id"))}
        if method == "queue.move":
            service.queue_move(_int(params, "id"), _int(params, "position"))
            return {}
        if method == "queue.retry":
            job_id = params.get("id")
            if job_id is not None and (not isinstance(job_id, int) or isinstance(job_id, bool)):
                raise ProtocolError(_t("Parameter 'id' muss eine Zahl oder null sein"))
            service.queue_retry(job_id)
            return {}
        if method == "queue.pause":
            service.queue_pause()
            return {}
        if method == "queue.resume":
            service.queue_resume()
            return {}
        if method == "shutdown":
            if service.busy() and not bool(params.get("force", False)):
                return {"stopping": False}
            log.info("Beenden angefordert")
            if self._on_shutdown is not None:
                self._on_shutdown()
            return {"stopping": True}
        raise ProtocolError(_t("Unbekannte Methode '{method}'", method=method))
