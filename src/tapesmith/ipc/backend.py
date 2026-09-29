"""Druck-Backends für alle Clients: über den Druckdienst p12d oder direkt.

`DaemonBackend` schickt Aufträge über die Pipe an den Dienst, `LocalBackend` nutzt die vorhandene
Pipeline im eigenen Prozess. `make_backend` entscheidet (Konfiguration, `TAPESMITH_NO_DAEMON`),
startet den Dienst bei Bedarf und fällt mit deutschem Hinweis auf den Direktdruck zurück.
Ohne Qt.
"""

from __future__ import annotations

import contextlib
import os
import threading
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from tapesmith.config import setting
from tapesmith.connection import ConnectionManager, ConnectionState
from tapesmith.daemon.queue import QueuedJob
from tapesmith.device.profile import DeviceProfile
from tapesmith.guard import load_policy
from tapesmith.ipc.client import DaemonClient, DaemonNotSent
from tapesmith.ipc.codec import (
    StateInfo,
    StatusReport,
    decode_outcome,
    decode_report,
    decode_state,
    encode_request,
)
from tapesmith.ipc.pipe import DaemonUnavailable
from tapesmith.ipc.protocol import ProtocolError
from tapesmith.jobs import CancelToken
from tapesmith.pipeline import PrintOutcome, PrintPipeline, PrintPlan, PrintRequest, RunSession
from tapesmith.status import FULL_QUERIES, PREFLIGHT_QUERIES, read_status
from tapesmith.i18n import N_, _t

EVENTS = ("state", "status", "queue", "job", "progress", "warning", "cut_pause")

REASON_OTHER_VERSION = N_("Druckdienst hat eine andere Version, direkt gedruckt ('p12 daemon restart')")
REASON_UNREACHABLE = N_("Druckdienst nicht erreichbar, drucke direkt")
REASON_LOST = N_("Druckdienst nicht mehr erreichbar (beendet oder neu gestartet), drucke direkt")

CANCEL_POLL_S = 0.05


class Relay:
    """Thread-sichere Rückruf-Verteilung (wie `gui.services.Relay`, ohne gui-Import)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._callbacks: list[Callable[..., None]] = []

    def connect(self, callback: Callable[..., None]) -> None:
        with self._lock:
            self._callbacks.append(callback)

    def disconnect(self, callback: Callable[..., None]) -> None:
        with self._lock:
            try:
                self._callbacks.remove(callback)
            except ValueError:
                pass

    def __call__(self, *args) -> None:
        with self._lock:
            callbacks = list(self._callbacks)
        for callback in callbacks:
            try:
                callback(*args)
            except Exception:  # noqa: BLE001 (ein fehlerhafter Abonnent darf die anderen nicht stören)
                pass


# ---------- Warteschlange ----------

@dataclass(frozen=True)
class QueueSnapshot:
    jobs: tuple[QueuedJob, ...]
    paused: bool
    auto_retry: bool
    next_try: datetime | None
    probe: str
    waiting_reason: str

    @staticmethod
    def from_dict(data: dict) -> "QueueSnapshot":
        try:
            jobs = tuple(QueuedJob.from_dict(item) for item in data.get("jobs", []))
            next_try = data.get("next_try")
            return QueueSnapshot(
                jobs=jobs,
                paused=bool(data.get("paused", False)),
                auto_retry=bool(data.get("auto_retry", True)),
                next_try=datetime.fromisoformat(next_try) if next_try else None,
                probe=str(data.get("probe", "")),
                waiting_reason=str(data.get("waiting_reason", "")),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ProtocolError(_t("Ungültige Warteschlange: {exc}", exc=exc)) from exc


class QueueOps(Protocol):
    def list(self, include_done: bool = False) -> QueueSnapshot: ...
    def cancel(self, job_id: int) -> bool: ...
    def duplicate(self, job_id: int) -> int: ...
    def move(self, job_id: int, position: int) -> None: ...
    def retry(self, job_id: int | None = None) -> None: ...
    def pause(self) -> None: ...
    def resume(self) -> None: ...


class PrintBackend(Protocol):
    kind: str
    fallback_reason: str

    def plan(self, request: PrintRequest) -> PrintPlan: ...

    def execute(self, request: PrintRequest, *, cancel: CancelToken | None = None,
                on_progress: Callable[[int, int], None] | None = None,
                on_warning: Callable[[str], None] | None = None,
                on_cut_pause: Callable[[str, int, int, float], None] | None = None,
                enqueue_on_offline: bool = False) -> PrintOutcome: ...

    def continue_cut(self) -> bool: ...
    def preconnect(self) -> None: ...
    def disconnect(self) -> None: ...
    def state_info(self) -> StateInfo: ...
    def query_status(self, *, quick: bool = False, fresh: bool = True) -> StatusReport: ...
    def lease(self, timeout_s: float = 120.0) -> AbstractContextManager[None]: ...
    def reload(self) -> None: ...
    def add_listener(self, event: str, callback: Callable[[object], None]) -> None: ...
    def remove_listener(self, event: str, callback) -> None: ...
    def queue_ops(self) -> QueueOps | None: ...
    def close(self) -> None: ...


def _check_event(event: str) -> None:
    if event not in EVENTS:
        raise ValueError(_t("Unbekanntes Ereignis '{event}' (erlaubt: {items})", event=event, items=', '.join(EVENTS)))


# ---------- Direkt ----------

class LocalBackend:
    """Druckt direkt im eigenen Prozess über die vorhandene Pipeline."""

    kind = "local"
    listen_s = 0.15          # Nachzügler-Wartezeit bei der Statusabfrage (CLI: p12 status --listen)

    def __init__(self, pipeline: PrintPipeline, *, warning_relay: Relay, cut_pause_relay: Relay,
                 state_relay: Relay | None = None, manager: ConnectionManager | None = None,
                 run_session: RunSession | None = None,
                 post_hooks: Sequence[Callable[[PrintOutcome], list[str]]] = (),
                 fallback_reason: str = "", now: Callable[[], datetime] = datetime.now):
        self._pipeline = pipeline
        self._warning_relay = warning_relay
        self._cut_pause_relay = cut_pause_relay
        self._manager = manager
        self._run_session = run_session
        self._post_hooks = list(post_hooks)
        self.fallback_reason = fallback_reason
        self._now = now
        self._events = {name: Relay() for name in EVENTS}
        self._wrappers: dict[tuple[str, int], Callable] = {}
        self._last_report: StatusReport | None = None
        if state_relay is not None:
            state_relay.connect(self._on_state)

    # --- Druck ---

    def plan(self, request: PrintRequest) -> PrintPlan:
        return self._pipeline.plan(request)

    def execute(self, request: PrintRequest, *, cancel: CancelToken | None = None,
                on_progress: Callable[[int, int], None] | None = None,
                on_warning: Callable[[str], None] | None = None,
                on_cut_pause: Callable[[str, int, int, float], None] | None = None,
                enqueue_on_offline: bool = False) -> PrintOutcome:
        job_key = uuid.uuid4().hex

        def warn(text: str) -> None:
            if on_warning is not None:
                on_warning(text)
            self._events["warning"]({"job_key": job_key, "text": text})

        def cut(state: str, done: int, total: int, seconds: float) -> None:
            if on_cut_pause is not None:
                on_cut_pause(state, done, total, seconds)
            self._events["cut_pause"]({"job_key": job_key, "state": state, "done": done, "total": total,
                                       "seconds": seconds})

        def progress(done: int, total: int) -> None:
            if on_progress is not None:
                on_progress(done, total)
            self._events["progress"]({"job_key": job_key, "done": done, "total": total})

        self._warning_relay.connect(warn)
        self._cut_pause_relay.connect(cut)
        try:
            outcome = self._pipeline.execute(request, cancel=cancel, on_progress=progress)
        finally:
            self._warning_relay.disconnect(warn)
            self._cut_pause_relay.disconnect(cut)
        if outcome.status == "ok":
            for hook in self._post_hooks:
                try:
                    notes = hook(outcome) or []
                except Exception as exc:  # noqa: BLE001 (ein Hook darf den Druck nie scheitern lassen)
                    notes = [_t("Nachbearbeitung fehlgeschlagen: {exc}", exc=exc)]
                for note in notes:
                    outcome.warnings.append(note)
                    try:
                        warn(note)
                    except Exception:  # noqa: BLE001
                        pass
        return outcome

    def continue_cut(self) -> bool:
        return self._pipeline.continue_after_cut()

    # --- Verbindung ---

    def preconnect(self) -> None:
        if self._manager is not None:
            self._manager.preconnect()

    def disconnect(self) -> None:
        if self._manager is not None:
            self._manager.disconnect()

    def _info(self, state: ConnectionState | str) -> StateInfo:
        manager = self._manager
        error = manager.last_error if manager is not None else None
        value = state.value if isinstance(state, ConnectionState) else str(state)
        return StateInfo(value, getattr(manager, "transport_name", None) if manager is not None else None,
                         str(error) if error is not None else None)

    def state_info(self) -> StateInfo:
        if self._manager is None:
            return StateInfo("getrennt")
        return self._info(self._manager.state)

    def _on_state(self, state) -> None:
        self._events["state"](self._info(state))

    def _runner(self) -> RunSession:
        if self._manager is not None:
            return self._manager.run
        if self._run_session is not None:
            return self._run_session
        return self._pipeline._run_session

    def query_status(self, *, quick: bool = False, fresh: bool = True) -> StatusReport:
        if not fresh:
            # Ohne Dienst gibt es keinen gemeinsamen Cache: letzter eigener Stand, kein Druckerkontakt.
            if self._last_report is not None:
                return StatusReport(self.state_info(), self._last_report.status, self._last_report.checked_at)
            return StatusReport(self.state_info(), None, None)
        profile = self._pipeline.profile
        queries = PREFLIGHT_QUERIES if quick else FULL_QUERIES
        listen = self.listen_s
        status = self._runner()(lambda session: read_status(session, profile, queries, listen))
        report = StatusReport(self.state_info(), status, self._now())
        self._last_report = report
        self._events["status"](report)
        return report

    @contextlib.contextmanager
    def lease(self, timeout_s: float = 120.0) -> Iterator[None]:
        if self._manager is not None:
            self._manager.disconnect()
        yield

    def reload(self) -> None:
        pass

    # --- Ereignisse ---

    def add_listener(self, event: str, callback: Callable[[object], None]) -> None:
        _check_event(event)
        self._events[event].connect(callback)

    def remove_listener(self, event: str, callback) -> None:
        if event in self._events:
            self._events[event].disconnect(callback)

    def queue_ops(self) -> QueueOps | None:
        return None

    def close(self) -> None:
        if self._manager is not None:
            self._manager.close()


# ---------- Über den Dienst ----------

class _DaemonQueueOps:
    def __init__(self, call: Callable[..., dict]):
        self._call = call

    def list(self, include_done: bool = False) -> QueueSnapshot:
        return QueueSnapshot.from_dict(self._call("queue.list", {"include_done": bool(include_done)}))

    def cancel(self, job_id: int) -> bool:
        return bool(self._call("queue.cancel", {"id": int(job_id)}).get("ok", False))

    def duplicate(self, job_id: int) -> int:
        return int(self._call("queue.duplicate", {"id": int(job_id)})["id"])

    def move(self, job_id: int, position: int) -> None:
        self._call("queue.move", {"id": int(job_id), "position": int(position)})

    def retry(self, job_id: int | None = None) -> None:
        self._call("queue.retry", {"id": int(job_id) if job_id is not None else None})

    def pause(self) -> None:
        self._call("queue.pause")

    def resume(self) -> None:
        self._call("queue.resume")


class DaemonBackend:
    """Druckt über den Druckdienst p12d; der Plan entsteht lokal (Anzeige), der Dienst prüft verbindlich.

    Mit `reconnect` überlebt das Backend einen Neustart des Dienstes (Absturz, `p12 daemon restart`,
    `p12 daemon stop`): ist der Kanal schon zu, bevor eine Anfrage raus geht (`DaemonNotSent`), wird
    einmal neu verbunden, die Listener werden neu angemeldet und die Anfrage wiederholt. Scheitert das
    Neuverbinden, wechselt das Backend mit `fallback` auf den Direktdruck (Hinweis als Warnung). Ging
    eine Anfrage schon raus und riss dann die Verbindung ab, wird nie wiederholt (`DaemonLost`).
    """

    def __init__(self, client: DaemonClient, *, planner: Callable[[PrintRequest], PrintPlan],
                 reconnect: Callable[[], DaemonClient] | None = None,
                 fallback: Callable[[str], PrintBackend] | None = None):
        self.client = client
        self._planner = planner
        self._reconnect = reconnect
        self._fallback = fallback
        self._local: PrintBackend | None = None
        self.fallback_reason = ""
        self._wrappers: dict[tuple[str, int], Callable[[dict], None]] = {}
        self._subscriptions: dict[tuple[str, int], tuple[str, Callable[[object], None]]] = {}
        self._lock = threading.Lock()
        self._reconnect_lock = threading.Lock()

    @property
    def kind(self) -> str:
        return "local" if self._local is not None else "daemon"

    # --- Neuverbinden ---

    def _renew(self, stale: DaemonClient) -> DaemonClient:
        """Neuer Client statt `stale` (einmal je abgerissener Verbindung, thread-sicher).

        Wirft `DaemonUnavailable`/`ProtocolError`, wenn der Dienst nicht erreichbar ist."""
        with self._reconnect_lock:
            if self.client is not stale:
                return self.client           # ein anderer Thread hat schon neu verbunden
            if self._reconnect is None:
                raise DaemonNotSent()
            fresh = self._reconnect()
            with self._lock:
                wrappers = [(key[0], wrapper) for key, wrapper in self._wrappers.items()]
            for event, wrapper in wrappers:
                fresh.add_listener(event, wrapper)
            self.client = fresh
        try:
            stale.close()
        except Exception:  # noqa: BLE001
            pass
        return fresh

    def _switch_to_local(self, exc: BaseException) -> PrintBackend | None:
        """Rückfall auf den Direktdruck; None ohne `fallback`."""
        reason = _t(REASON_OTHER_VERSION) if isinstance(exc, ProtocolError) else _t(REASON_LOST)
        with self._reconnect_lock:
            if self._local is not None:
                return self._local
            if self._fallback is None:
                return None
            local = self._fallback(reason)
            with self._lock:
                subscriptions = list(self._subscriptions.values())
            for event, callback in subscriptions:
                local.add_listener(event, callback)
            self.fallback_reason = reason
            self._local = local
        return local

    def _call(self, method: str, params: dict | None = None, *, timeout: float | None = 30.0) -> dict:
        client = self.client
        try:
            return client.call(method, params, timeout=timeout)
        except DaemonNotSent:
            if self._reconnect is None:
                raise
        return self._renew(client).call(method, params, timeout=timeout)

    def _route(self, method: str, params: dict | None = None) -> tuple[PrintBackend | None, dict]:
        """(Direktdruck-Backend, {}) nach einem Rückfall, sonst (None, Antwort des Dienstes)."""
        if self._local is not None:
            return self._local, {}
        try:
            return None, self._call(method, params)
        except (DaemonUnavailable, ProtocolError) as exc:
            local = self._switch_to_local(exc)
            if local is None:
                raise
            return local, {}

    # --- Druck ---

    def plan(self, request: PrintRequest) -> PrintPlan:
        return self._planner(request)

    def execute(self, request: PrintRequest, *, cancel: CancelToken | None = None,
                on_progress: Callable[[int, int], None] | None = None,
                on_warning: Callable[[str], None] | None = None,
                on_cut_pause: Callable[[str, int, int, float], None] | None = None,
                enqueue_on_offline: bool = False) -> PrintOutcome:
        kwargs = dict(cancel=cancel, on_progress=on_progress, on_warning=on_warning,
                      on_cut_pause=on_cut_pause, enqueue_on_offline=enqueue_on_offline)
        if self._local is not None:
            return self._local.execute(request, **kwargs)
        client = self.client
        try:
            return self._execute_on(client, request, **kwargs)
        except DaemonNotSent:
            if self._reconnect is None:
                raise
        try:
            client = self._renew(client)
        except (DaemonUnavailable, ProtocolError) as exc:
            local = self._switch_to_local(exc)
            if local is None:
                raise
            if on_warning is not None:
                on_warning(self.fallback_reason)
            outcome = local.execute(request, **kwargs)
            if on_warning is None and self.fallback_reason not in outcome.warnings:
                outcome.warnings.insert(0, self.fallback_reason)   # z. B. Tray: Hinweis in der Meldung
            return outcome
        return self._execute_on(client, request, **kwargs)

    def _execute_on(self, client: DaemonClient, request: PrintRequest, *, cancel: CancelToken | None,
                    on_progress, on_warning, on_cut_pause, enqueue_on_offline: bool) -> PrintOutcome:
        job_key = uuid.uuid4().hex
        plan = self._planner(request)
        encoded = encode_request(request)

        def mine(data: dict) -> bool:
            return data.get("job_key") == job_key

        def progress(data: dict) -> None:
            if on_progress is not None and mine(data):
                on_progress(int(data.get("done", 0)), int(data.get("total", 0)))

        def warning(data: dict) -> None:
            if on_warning is not None and mine(data):
                on_warning(str(data.get("text", "")))

        def cut_pause(data: dict) -> None:
            if on_cut_pause is not None and mine(data):
                on_cut_pause(str(data.get("state", "")), int(data.get("done", 0)), int(data.get("total", 0)),
                             float(data.get("seconds", 0.0)))

        listeners = (("progress", progress), ("warning", warning), ("cut_pause", cut_pause))
        for name, callback in listeners:
            client.add_listener(name, callback)
        finished = threading.Event()
        watcher = None
        if cancel is not None:
            watcher = threading.Thread(target=self._watch_cancel, args=(client, cancel, finished, job_key),
                                       name="p12-abbruch-waechter", daemon=True)
            watcher.start()
        try:
            result = client.call("print", {"job_key": job_key, "request": encoded,
                                           "enqueue_on_offline": bool(enqueue_on_offline)}, timeout=None)
        finally:
            finished.set()
            for name, callback in listeners:
                client.remove_listener(name, callback)
            if watcher is not None:
                watcher.join(1)
        return decode_outcome(result, plan)

    @staticmethod
    def _watch_cancel(client: DaemonClient, cancel: CancelToken, finished: threading.Event,
                      job_key: str) -> None:
        while not finished.is_set():
            if cancel.wait(CANCEL_POLL_S):
                if finished.is_set():
                    return
                try:
                    client.call("cancel", {"job_key": job_key}, timeout=10.0)
                except Exception:  # noqa: BLE001 (Antwort des print-Aufrufs zählt)
                    pass
                return

    def continue_cut(self) -> bool:
        local, result = self._route("continue_cut")
        return local.continue_cut() if local is not None else bool(result.get("was_pausing", False))

    def preconnect(self) -> None:
        local, _result = self._route("preconnect")
        if local is not None:
            local.preconnect()

    def disconnect(self) -> None:
        local, _result = self._route("disconnect")
        if local is not None:
            local.disconnect()

    def state_info(self) -> StateInfo:
        local, result = self._route("state")
        return local.state_info() if local is not None else decode_state(result)

    def query_status(self, *, quick: bool = False, fresh: bool = True) -> StatusReport:
        local, result = self._route("status", {"quick": bool(quick), "fresh": bool(fresh)})
        return local.query_status(quick=quick, fresh=fresh) if local is not None else decode_report(result)

    @contextlib.contextmanager
    def lease(self, timeout_s: float = 120.0) -> Iterator[None]:
        if self._local is not None:
            with self._local.lease(timeout_s):
                yield
            return
        client = self.client
        try:
            lease_id = client.call("lease", {"timeout_s": float(timeout_s)})["lease_id"]
        except DaemonNotSent:
            if self._reconnect is None:
                raise
            client = self._renew(client)
            lease_id = client.call("lease", {"timeout_s": float(timeout_s)})["lease_id"]
        try:
            yield
        finally:
            client.call("release", {"lease_id": lease_id})

    def reload(self) -> None:
        local, _result = self._route("reload")
        if local is not None:
            local.reload()

    def add_listener(self, event: str, callback: Callable[[object], None]) -> None:
        _check_event(event)
        if event == "state":
            def wrapper(data: dict) -> None:
                callback(decode_state(data))
        elif event == "status":
            def wrapper(data: dict) -> None:
                callback(decode_report(data))
        else:
            wrapper = callback
        with self._lock:
            self._wrappers[(event, id(callback))] = wrapper
            self._subscriptions[(event, id(callback))] = (event, callback)
        self.client.add_listener(event, wrapper)
        if self._local is not None:
            self._local.add_listener(event, callback)

    def remove_listener(self, event: str, callback) -> None:
        with self._lock:
            wrapper = self._wrappers.pop((event, id(callback)), None)
            self._subscriptions.pop((event, id(callback)), None)
        if wrapper is not None:
            self.client.remove_listener(event, wrapper)
        if self._local is not None:
            self._local.remove_listener(event, callback)

    def queue_ops(self) -> QueueOps | None:
        if self._local is not None:
            return self._local.queue_ops()
        return _DaemonQueueOps(self._call)

    def close(self) -> None:
        self.client.close()
        if self._local is not None:
            self._local.close()


# ---------- Auswahl ----------

def _no_print(_fn):
    raise RuntimeError(_t("Planer druckt nicht"))


def local_planner(cfg: dict, profile: DeviceProfile) -> Callable[[PrintRequest], PrintPlan]:
    """Plan für Anzeige/Vorschau ohne Verlauf/Kontingent; der Dienst prüft verbindlich."""
    return PrintPipeline(profile, run_session=_no_print, policy=load_policy(cfg)).plan


def use_daemon(cfg: dict, *, env: Mapping[str, str] = os.environ) -> bool:
    if env.get("TAPESMITH_NO_DAEMON") == "1":
        return False
    return bool(setting(cfg, "daemon.enabled"))


def _connect_daemon(cfg: dict, *, client: str, allow_spawn: bool,
                    connector: Callable[..., DaemonClient],
                    launcher: Callable[..., DaemonClient] | None) -> DaemonClient:
    """Mit dem Dienst verbinden, bei Bedarf (und wenn erlaubt) starten. Wirft bei Misserfolg."""
    try:
        return connector(client=client, timeout_s=float(setting(cfg, "daemon.connect_timeout_s")))
    except DaemonUnavailable:
        if not (allow_spawn and setting(cfg, "daemon.spawn")):
            raise
    if launcher is None:
        from tapesmith.ipc.launcher import ensure_daemon

        return ensure_daemon(cfg, client=client, connector=connector)
    return launcher(cfg, client=client)


def make_backend(cfg: dict, profile: DeviceProfile, *, client: str,
                 local_factory: Callable[[str], PrintBackend], allow_spawn: bool = True,
                 env: Mapping[str, str] = os.environ,
                 connector: Callable[..., DaemonClient] = DaemonClient.connect,
                 launcher: Callable[..., DaemonClient] | None = None,
                 planner: Callable[[PrintRequest], PrintPlan] | None = None) -> PrintBackend:
    if not use_daemon(cfg, env=env):
        return local_factory("")

    def connect() -> DaemonClient:
        return _connect_daemon(cfg, client=client, allow_spawn=allow_spawn, connector=connector,
                               launcher=launcher)

    def reconnect() -> DaemonClient:
        try:
            return connect()
        except (DaemonUnavailable, ProtocolError):
            raise
        except Exception as exc:  # noqa: BLE001 (jeder andere Fehler heißt: nicht erreichbar)
            raise DaemonUnavailable(str(exc)) from exc

    try:
        daemon = connect()
    except ProtocolError:
        return local_factory(_t(REASON_OTHER_VERSION))
    except Exception:  # noqa: BLE001 (jeder andere Fehler: direkt drucken)
        return local_factory(_t(REASON_UNREACHABLE))
    return DaemonBackend(daemon, planner=planner or local_planner(cfg, profile), reconnect=reconnect,
                         fallback=local_factory)
