"""Druckdienst-Kern: nimmt Druckaufträge aller Clients an und führt sie
strikt nacheinander über die vorhandene `PrintPipeline` + `ConnectionManager` aus.

Qt-frei. Der Dienst ist alleiniger Inhaber der Druckerverbindung: Fehldruckschutz, Preflight,
Verlauf, Restmeter- und Schwarzanteil-Hooks, Schneidpause und Archiv-Hook laufen wie in GUI und CLI.
Offline-Aufträge landen auf Wunsch in der Warteschlange, sensible nie auf der Platte.
Ereignisse (Zustand, Status, Fortschritt, Warnungen, Schneidpause, Auftragsphasen, Warteschlange)
gehen über `emit` an alle Clients.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from typing import TYPE_CHECKING, Any

from tapesmith import archive, backup, config, paths
from tapesmith.config import setting
from tapesmith.connection import ConnectionManager, ConnectionState
from tapesmith.device.profile import DeviceProfile, load_profile
from tapesmith.guard import Debouncer, load_policy
from tapesmith.history import HistoryStore
from tapesmith.ipc.codec import StateInfo, StatusReport, encode_report, encode_request, encode_state
from tapesmith.jobs import CancelToken
from tapesmith.lock import PrinterBusy, PrintLock
from tapesmith.pipeline import PrintOutcome, PrintPipeline, PrintRequest, manager_runner
from tapesmith.printer import PrinterSession
from tapesmith.printhooks import print_hooks
from tapesmith.status import FULL_QUERIES, PREFLIGHT_QUERIES, PrinterStatus, read_status
from tapesmith.tape.profiles import current_tape
from tapesmith.tape.rolls import RollStore
from tapesmith.transport.base import ConnectTimeout, Transport
from tapesmith.transport.resolve import open_transport

from tapesmith.daemon.queue import JobQueue
from tapesmith.i18n import N_, _t

if TYPE_CHECKING:  # pragma: no cover
    from tapesmith.daemon.runner import QueueRunner

log = logging.getLogger(__name__)

LEASE_BUSY = N_("Drucker ist für Einrichtung/Diagnose reserviert")
LOCK_BUSY = N_("Drucker ist belegt, ein Auftrag läuft gerade")
OFFLINE_QUEUED = N_("Drucker nicht erreichbar, Auftrag wartet in der Warteschlange (#{})")
LEASE_QUEUED = N_("Drucker ist für Einrichtung/Diagnose reserviert, Auftrag wartet in der Warteschlange (#{})")
CONFIG_BROKEN = N_("Konfiguration fehlerhaft, vorige Einstellungen gelten: {}")
LEASE_WAIT_S = 30.0
PROGRESS_INTERVAL_S = 0.1
_LOCK_POLL_S = 0.05

# Änderungen an diesen Schlüsseln erfordern einen neuen Verbindungsmanager.
RECONNECT_TIMEOUT_S = 15.0
_CONNECTION_KEYS = ("transport", "mac", "connect_timeout_s", "idle_timeout_s")

TransportFactory = Callable[[dict, DeviceProfile], Callable[[], Transport]]


def default_transport_factory(cfg: dict, profile: DeviceProfile) -> Callable[[], Transport]:
    """Transport aus der Config; `transport == "ble"` mit gemerkter `ble.address` -> "ble:<adresse>"."""
    spec = cfg["transport"]
    address = setting(cfg, "ble.address")
    if spec == "ble" and address:
        spec = "ble:" + address
    return lambda: open_transport(
        spec, cfg["mac"], None, open_timeout=float(cfg["connect_timeout_s"]),
        experimental=frozenset(profile.experimental), ble_names=tuple(setting(cfg, "ble.names")),
        ble_scan_timeout_s=setting(cfg, "ble.scan_timeout_s"))


def _default_profile_loader() -> DeviceProfile:
    return load_profile(calibration_path=paths.calibration_path())


def _merge_keep_connection(new: dict, old: dict) -> dict:
    """Neue Konfiguration, aber mit den Verbindungsschlüsseln (und `ble`) der alten: die
    Verbindung wird erst beim Neuaufbau unter der Dienst-Sperre umgestellt."""
    return {**new, **{key: old[key] for key in (*_CONNECTION_KEYS, "ble") if key in old}}


def _mtime(path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


@dataclass
class _Lease:
    id: str
    owner: object
    expires: float


class PrintService:
    def __init__(self, *, config_loader: Callable[[], dict] = config.load_config,
                 profile_loader: Callable[[], DeviceProfile] | None = None,
                 transport_factory: TransportFactory | None = None,
                 lock_factory: Callable[[], Any] = PrintLock,
                 session_factory: Callable[..., PrinterSession] = PrinterSession,
                 sleep: Callable[[float], None] = time.sleep,
                 history: HistoryStore | None = None, queue: JobQueue | None = None,
                 rolls: RollStore | None = None,
                 archive_factory: Callable[[dict], Callable | None] = archive.archive_hook,
                 now: Callable[[], datetime] = datetime.now, clock: Callable[[], float] = time.monotonic,
                 emit: Callable[[str, dict], None] | None = None, debounce_s: float = 1.5,
                 watch_files: bool = True):
        self._config_loader = config_loader
        self._profile_loader = profile_loader or _default_profile_loader
        self._transport_factory = transport_factory or default_transport_factory
        self._lock_factory = lock_factory
        self._session_factory = session_factory
        self._sleep = sleep
        self._archive_factory = archive_factory
        self._now = now
        self._clock = clock
        self._emit_fn = emit
        self._extra_emitters: tuple[Callable[[str, dict], None], ...] = ()
        self._watch_files = watch_files

        self._cfg = config_loader()
        self._profile = self._profile_loader()
        self._own_history = history is None
        self._history = history if history is not None else HistoryStore()
        self._own_queue = queue is None
        self._queue = queue if queue is not None else JobQueue()
        self._rolls = rolls if rolls is not None else RollStore(tape=lambda: current_tape(self._cfg).id)
        self._debouncer = Debouncer(debounce_s, clock=clock)

        self._job_lock = threading.Lock()          # Dienst-Sperre: Aufträge strikt nacheinander
        self._state_lock = threading.Lock()        # schützt Tokens, Lease, Zähler, Cache
        self._tokens: dict[str, CancelToken] = {}
        self._current_key: str | None = None
        self._active = 0                           # Aufträge, die laufen oder auf die Sperre warten
        self._lease: _Lease | None = None
        self._status_cache: tuple[PrinterStatus, datetime] | None = None
        self._runner: QueueRunner | None = None
        self._reload_requested = False
        self._mtimes = self._file_mtimes()
        self._last_active = clock()
        self._last_daily = None
        self._closed = False

        self._manager: ConnectionManager | None = None
        self._pipeline: PrintPipeline | None = None
        self._archive = None
        self._build()

    # ---------- Aufbau ----------

    def _build(self) -> None:
        cfg, profile = self._cfg, self._profile
        self._manager = ConnectionManager(
            self._transport_factory(cfg, profile), profile,
            idle_timeout_s=float(cfg["idle_timeout_s"]), connect_timeout_s=float(cfg["connect_timeout_s"]),
            lock_factory=self._lock_factory, session_factory=self._session_factory, sleep=self._sleep,
            on_state=self._on_state)
        self._pipeline = PrintPipeline(
            profile, manager_runner(self._manager), history=self._history, policy=load_policy(cfg),
            debouncer=self._debouncer, preflight=True, on_warning=self._route_warning, now=self._now,
            on_cut_pause=self._route_cut_pause, cut_pause_s=cfg.get("cut_pause_s"),
            **print_hooks(self._rolls, lambda: current_tape(self._cfg).id))
        self._archive = self._make_archive(cfg)

    def _make_archive(self, cfg: dict):
        try:
            return self._archive_factory(cfg)
        except Exception as exc:  # noqa: BLE001 (Archiv darf den Dienst nie stören)
            log.warning("Archiv-Hook nicht verfügbar: %s", exc)
            return None

    def _file_mtimes(self) -> tuple:
        if not self._watch_files:
            return ()
        return (_mtime(paths.config_path()), _mtime(paths.calibration_path()))

    @staticmethod
    def _connection_signature(cfg: dict, profile: DeviceProfile) -> tuple:
        ble = cfg.get("ble")
        return (tuple(repr(cfg.get(key)) for key in _CONNECTION_KEYS),
                repr(sorted(ble.items())) if isinstance(ble, dict) else repr(ble),
                tuple(profile.experimental))

    def _maybe_reload(self, force: bool = False) -> None:
        """Nur unter der Dienst-Sperre: Config/Kalibrierung bei Änderung neu laden."""
        mtimes = self._file_mtimes()
        if not (force or self._reload_requested or mtimes != self._mtimes):
            return
        self._reload_requested = False
        self._mtimes = mtimes
        try:
            cfg = self._config_loader()
            profile = self._profile_loader()
            policy = load_policy(cfg)
        except Exception as exc:  # noqa: BLE001 (alte Einstellungen behalten)
            log.warning("Konfiguration fehlerhaft: %s", exc)
            self._route_warning(_t(CONFIG_BROKEN).format(exc))
            return
        rebuild = self._connection_signature(cfg, profile) != self._connection_signature(self._cfg, self._profile)
        self._cfg, self._profile = cfg, profile
        self._reconfigure_runner(cfg)
        if rebuild:
            log.info("Verbindungseinstellungen geändert, Verbindung wird neu aufgebaut")
            old = self._manager
            self._build()
            if old is not None:
                old.close()
            self._emit("state", encode_state(self.state()))
            return
        self._pipeline.set_policy(policy)
        self._pipeline.set_profile(profile)
        self._pipeline.set_cut_pause(cfg.get("cut_pause_s"))
        self._manager.set_profile(profile)
        self._archive = self._make_archive(cfg)

    def _reconfigure_runner(self, cfg: dict) -> None:
        """Automatischer Nachdruck, Backoff und Probe gelten sofort, nicht erst nach Neustart."""
        reconfigure = getattr(self._runner, "reconfigure", None)
        if reconfigure is None:
            return
        try:
            reconfigure(cfg)
        except Exception as exc:  # noqa: BLE001 (alte Läufer-Einstellungen bleiben aktiv)
            log.warning("Warteschlangen-Einstellungen nicht übernommen: %s", exc)

    # ---------- Eigenschaften ----------

    @property
    def profile(self) -> DeviceProfile:
        return self._profile

    @property
    def config(self) -> dict:
        return self._cfg

    @property
    def queue(self) -> JobQueue:
        return self._queue

    @property
    def manager(self) -> ConnectionManager:
        return self._manager

    @property
    def pipeline(self) -> PrintPipeline:
        return self._pipeline

    @property
    def history(self) -> HistoryStore:
        return self._history

    @property
    def rolls(self) -> RollStore:
        return self._rolls

    @property
    def closed(self) -> bool:
        return self._closed

    def set_emitter(self, emit: Callable[[str, dict], None]) -> None:
        """Ersetzt den Haupt-Empfänger (setzt der Pipe-Server)."""
        self._emit_fn = emit

    def add_emitter(self, fn: Callable[[str, dict], None]) -> None:
        """Zusätzlicher Ereignis-Empfänger (z. B. der SSE-Broker der Web-API)."""
        with self._state_lock:
            self._extra_emitters = (*self._extra_emitters, fn)

    def attach_runner(self, runner: QueueRunner) -> None:
        self._runner = runner

    # ---------- Ereignisse ----------

    def _emit(self, event: str, data: dict) -> None:
        for emit in (self._emit_fn, *self._extra_emitters):
            if emit is None:
                continue
            try:
                emit(event, data)
            except Exception:  # noqa: BLE001 (Ereignisse dürfen den Druck nie stören)
                log.exception("Ereignis %s nicht zugestellt", event)

    def _on_state(self, _state: ConnectionState) -> None:
        self._emit("state", encode_state(self.state()))

    def _route_warning(self, text: str) -> None:
        self._emit("warning", {"job_key": self._current_key, "text": text})

    def _route_cut_pause(self, state: str, done: int, total: int, seconds: float) -> None:
        self._emit("cut_pause", {"job_key": self._current_key, "state": state, "done": done,
                                 "total": total, "seconds": seconds})

    def _job_event(self, key: str, phase: str, request: PrintRequest, status: str = "",
                   queue_id: int | None = None) -> None:
        self._emit("job", {"job_key": key, "phase": phase, "status": status,
                           "source": request.meta.source, "title": request.meta.title,
                           "queue_id": queue_id})

    def _queue_event(self) -> None:
        self._emit("queue", {})

    # ---------- Drucken ----------

    def _acquire_job_lock(self, token: CancelToken | None, timeout_s: float | None = None) -> bool:
        """Wartet auf die Dienst-Sperre; False bei Abbruch (Token) oder Zeitablauf."""
        deadline = None if timeout_s is None else time.monotonic() + timeout_s
        while True:
            if token is not None and token.cancelled:
                return False
            wait = _LOCK_POLL_S
            if deadline is not None:
                rest = deadline - time.monotonic()
                if rest <= 0:
                    return False
                wait = min(wait, rest)
            if self._job_lock.acquire(timeout=wait):
                if token is not None and token.cancelled:
                    self._job_lock.release()
                    return False
                return True

    def _enqueue(self, request: PrintRequest) -> int:
        meta = request.meta
        queue_id = self._queue.add({"request": encode_request(replace(request, confirmed=True))},
                                   source=meta.source, title=meta.title, sensitive=meta.sensitive)
        log.info("Auftrag in die Warteschlange (#%s): %s", queue_id,
                 "(sensibel)" if meta.sensitive else meta.title)
        self._queue_event()
        return queue_id

    def _queued_outcome(self, request: PrintRequest, plan, text: str) -> PrintOutcome:
        queue_id = self._enqueue(request)
        warning = text.format(queue_id)
        return PrintOutcome("wartet", plan, warnings=[warning], queue_id=queue_id)

    def _queue_enabled(self) -> bool:
        return bool(setting(self._cfg, "queue.enabled"))

    def submit(self, request: PrintRequest, *, job_key: str, enqueue_on_offline: bool = False,
               from_queue: bool = False) -> PrintOutcome:
        token = CancelToken()
        with self._state_lock:
            self._tokens[job_key] = token
            self._active += 1
        self._touch()
        self._job_event(job_key, "angenommen", request)
        status = "fehler"
        queue_id = None
        try:
            outcome = self._submit(request, job_key, token, enqueue_on_offline, from_queue)
            status = outcome.status
            queue_id = outcome.queue_id
            return outcome
        finally:
            with self._state_lock:
                if self._tokens.get(job_key) is token:
                    del self._tokens[job_key]
                self._active -= 1
            self._touch()
            self._job_event(job_key, "fertig", request, status, queue_id)

    def _submit(self, request: PrintRequest, job_key: str, token: CancelToken,
                enqueue_on_offline: bool, from_queue: bool) -> PrintOutcome:
        if self.leased:
            return self._submit_leased(request, enqueue_on_offline and not from_queue)
        if not self._acquire_job_lock(token):
            return PrintOutcome("abgebrochen", self._pipeline.plan(request))
        try:
            if self.leased:   # Lease kam, während der Auftrag wartete
                return self._submit_leased(request, enqueue_on_offline and not from_queue)
            self._maybe_reload()
            self._current_key = job_key
            self._job_event(job_key, "läuft", request)
            if not request.meta.sensitive:
                log.info("Auftrag %s läuft: %s", job_key, request.meta.title)
            progress = _Progress(self, job_key)
            pipeline = self._pipeline
            try:
                if from_queue:
                    # Der Läufer hat seinen eigenen Backoff; die schnelle Offline-Sperre des
                    # Managers (10 s) gilt hier nicht.
                    self._manager.connect(force=True)
                outcome = pipeline.execute(request, cancel=token, on_progress=progress,
                                           debounce=not from_queue)
            except ConnectTimeout:
                progress.flush()
                if from_queue or not enqueue_on_offline or not self._queue_enabled():
                    raise
                outcome = self._queued_outcome(request, pipeline.plan(request), _t(OFFLINE_QUEUED))
                if self._runner is not None:
                    self._runner.notify_offline()
                return outcome
            progress.flush()
            if outcome.status == "ok":
                self._after_ok(outcome)
            return outcome
        finally:
            self._current_key = None
            self._job_lock.release()

    def _submit_leased(self, request: PrintRequest, may_enqueue: bool) -> PrintOutcome:
        if not (may_enqueue and self._queue_enabled()):
            raise PrinterBusy(_t(LEASE_BUSY))
        plan = self._pipeline.plan(request)
        decision = plan.decision
        if not decision.allowed:
            return PrintOutcome("abgelehnt", plan, reasons=decision.reasons)
        if decision.needs_confirmation and not request.confirmed:
            return PrintOutcome("bestätigung_nötig", plan, reasons=decision.reasons)
        return self._queued_outcome(request, plan, _t(LEASE_QUEUED))

    def _after_ok(self, outcome: PrintOutcome) -> None:
        hook = self._archive
        if hook is not None:
            try:
                notes = hook(outcome) or []
            except Exception as exc:  # noqa: BLE001 (ein Druck scheitert nie am Archiv)
                notes = [_t("Archiv: {exc}", exc=exc)]
            for note in notes:
                outcome.warnings.append(note)
                self._route_warning(note)
        if outcome.printer_status is not None:
            self._store_status(outcome.printer_status)
        runner = self._runner
        if runner is not None and self._queue.active_count() > 0:
            try:
                runner.notify_online()
            except Exception:  # noqa: BLE001
                log.exception("Warteschlangen-Läufer nicht benachrichtigt")

    def cancel(self, job_key: str) -> bool:
        with self._state_lock:
            token = self._tokens.get(job_key)
        if token is None:
            return False
        token.cancel()
        return True

    def continue_cut(self) -> bool:
        return self._pipeline.continue_after_cut()

    def busy(self) -> bool:
        with self._state_lock:
            return self._active > 0 or self._job_lock.locked()

    # ---------- Verbindung und Status ----------

    def preconnect(self) -> None:
        if self.leased:
            return
        self._manager.preconnect()

    def disconnect(self) -> None:
        self._manager.disconnect()

    def state(self) -> StateInfo:
        manager = self._manager
        error = manager.last_error
        return StateInfo(manager.state.value, manager.transport_name,
                         str(error) if error is not None else None, self.leased)

    def _store_status(self, status: PrinterStatus) -> None:
        with self._state_lock:
            self._status_cache = (status, self._now())
        self._emit("status", encode_report(self._report()))

    def _report(self) -> StatusReport:
        with self._state_lock:
            cache = self._status_cache
        status, checked = cache if cache is not None else (None, None)
        return StatusReport(self.state(), status, checked)

    def status(self, *, quick: bool = False, fresh: bool = True, force: bool = False,
               reconnect: bool = False) -> StatusReport:
        """Druckerstatus. `force` (Läufer): Offline-Sperre des Managers umgehen. `reconnect`
        („Erneut verbinden“): Sperre umgehen und mit längerer Wartezeit verbinden, weil ein gerade
        aufgewachter Drucker für den Bluetooth-Aufbau oft länger braucht."""
        if not fresh:
            return self._report()
        if self.leased:
            raise PrinterBusy(_t(LEASE_BUSY))
        with self._state_lock:
            self._active += 1
        try:
            self._job_lock.acquire()
            try:
                if self.leased:
                    raise PrinterBusy(_t(LEASE_BUSY))
                self._maybe_reload()
                profile = self._profile
                queries = PREFLIGHT_QUERIES if quick else FULL_QUERIES
                if reconnect:
                    wait_s = max(float(self._cfg["connect_timeout_s"]), RECONNECT_TIMEOUT_S)
                    factory = self._transport_factory({**self._cfg, "connect_timeout_s": wait_s}, profile)
                    self._manager.connect(timeout=wait_s + 5.0, force=True, factory=factory)
                elif force:
                    self._manager.connect(force=True)
                status = self._manager.run(lambda s: read_status(s, profile, queries))
            finally:
                self._job_lock.release()
        finally:
            with self._state_lock:
                self._active -= 1
            self._touch()
        self._store_status(status)
        return self._report()

    # ---------- Reservierung (Lease) ----------

    @property
    def leased(self) -> bool:
        with self._state_lock:
            lease = self._lease
        return lease is not None and self._clock() < lease.expires

    def lease(self, owner: object, timeout_s: float = 120.0) -> str:
        if self.leased:
            raise PrinterBusy(_t(LEASE_BUSY))
        if not self._acquire_job_lock(None, LEASE_WAIT_S):
            raise PrinterBusy(_t(LOCK_BUSY))
        try:
            with self._state_lock:
                if self._lease is not None and self._clock() < self._lease.expires:
                    raise PrinterBusy(_t(LEASE_BUSY))
            self._manager.disconnect()
            lease = _Lease(uuid.uuid4().hex, owner, self._clock() + float(timeout_s))
            with self._state_lock:
                self._lease = lease
        finally:
            self._job_lock.release()
        log.info("Drucker reserviert (%.0f s)", timeout_s)
        self._emit("state", encode_state(self.state()))
        return lease.id

    def _drop_lease(self, match: Callable[[_Lease], bool]) -> bool:
        with self._state_lock:
            lease = self._lease
            if lease is None or not match(lease):
                return False
            self._lease = None
        self._touch()
        log.info("Reservierung aufgehoben")
        self._emit("state", encode_state(self.state()))
        runner = self._runner
        if runner is not None:
            runner.wake()
        return True

    def release(self, lease_id: str) -> None:
        self._drop_lease(lambda lease: lease.id == lease_id)

    def release_owner(self, owner: object) -> None:
        self._drop_lease(lambda lease: lease.owner is owner)

    # ---------- Konfiguration ----------

    def reload(self) -> DeviceProfile:
        with self._job_lock:
            self._maybe_reload(force=True)
        return self._profile

    def request_reload(self) -> None:
        """Einstellungen sofort übernehmen, ohne zu blockieren (z. B. nach PATCH /settings).

        Läufer (Auto-Nachdruck, Backoff, Probe) und `config`/`queue_snapshot` zeigen die neuen
        Werte sofort; die Verbindungsschlüssel bleiben bis zum Neuaufbau alt. Pipeline-Policy,
        Profil, Schneidpause, Archiv und ein eventueller Verbindungs-Neuaufbau folgen sofort, wenn
        die Dienst-Sperre frei ist, sonst vor dem nächsten Auftrag.
        """
        try:
            cfg = self._config_loader()
        except Exception as exc:  # noqa: BLE001 (alte Einstellungen behalten)
            log.warning("Konfiguration fehlerhaft: %s", exc)
            self._route_warning(_t(CONFIG_BROKEN).format(exc))
            return
        self._reconfigure_runner(cfg)
        self._cfg = _merge_keep_connection(cfg, self._cfg)
        self._reload_requested = True
        if self._job_lock.acquire(blocking=False):
            try:
                self._maybe_reload(force=True)
            finally:
                self._job_lock.release()
        self._emit("state", encode_state(self.state()))

    # ---------- Warteschlange ----------

    def queue_snapshot(self, include_done: bool = False) -> dict:
        runner = self._runner
        next_try = runner.next_try() if runner is not None else self._queue.earliest_next_try()
        return {
            "jobs": [job.to_dict() for job in self._queue.list(include_done=include_done)],
            "paused": self._queue.paused,
            "auto_retry": bool(runner.auto_retry if runner is not None and hasattr(runner, "auto_retry")
                               else setting(self._cfg, "queue.auto_retry")),
            "next_try": next_try.isoformat(timespec="seconds") if next_try is not None else None,
            "probe": runner.probe_name if runner is not None else str(setting(self._cfg, "queue.probe")),
            "waiting_reason": runner.last_reason if runner is not None else "",
        }

    def queue_cancel(self, job_id: int) -> bool:
        ok = self._queue.cancel(job_id)
        if ok:
            self.cancel(f"queue-{job_id}")
            self._queue_event()
        return ok

    def queue_duplicate(self, job_id: int) -> int:
        new_id = self._queue.duplicate(job_id)
        self._queue_event()
        self._wake_runner()
        return new_id

    def queue_move(self, job_id: int, position: int) -> None:
        self._queue.move(job_id, position)
        self._queue_event()

    def queue_retry(self, job_id: int | None) -> None:
        self._queue.retry_now(job_id)
        self._queue_event()
        self._wake_runner(manual=True)

    def queue_pause(self) -> None:
        self._queue.pause()
        self._queue_event()

    def queue_resume(self) -> None:
        self._queue.resume()
        self._queue_event()
        self._wake_runner()

    def _wake_runner(self, manual: bool = False) -> None:
        runner = self._runner
        if runner is not None:
            runner.wake(manual=manual)

    # ---------- Haushalt ----------

    def _touch(self) -> None:
        self._last_active = self._clock()

    def idle_since(self) -> float | None:
        if self.busy() or self.leased:
            return None
        if self._manager.state in (ConnectionState.CONNECTED, ConnectionState.CONNECTING):
            return None
        try:
            if self._queue.active_count() > 0:
                return None
        except Exception:  # noqa: BLE001
            return None
        return self._last_active

    def housekeeping(self, now: datetime | None = None) -> None:
        try:
            with self._state_lock:
                lease = self._lease
            if lease is not None and self._clock() >= lease.expires:
                log.info("Reservierung abgelaufen")
                self._drop_lease(lambda current: current is lease)
        except Exception:  # noqa: BLE001
            log.exception("Haushalt: Reservierung")
        now = now or self._now()
        if self._last_daily == now.date():
            return
        self._last_daily = now.date()
        try:
            path = backup.maybe_auto_backup(self._cfg, now)
            if path is not None:
                log.info("Tagessicherung geschrieben: %s", path)
        except Exception:  # noqa: BLE001
            log.exception("Haushalt: Tagessicherung")
        try:
            purged = self._queue.purge_done()
            if purged:
                self._queue_event()
        except Exception:  # noqa: BLE001
            log.exception("Haushalt: Warteschlange aufräumen")

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        runner = self._runner
        try:
            if runner is not None and runner.stop() is False:
                log.warning("Warteschlangen-Läufer hat nicht rechtzeitig angehalten, "
                            "Warteschlange wird trotzdem geschlossen")
        finally:
            try:
                self._manager.close()
            finally:
                if self._own_queue:
                    self._queue.close()
                if self._own_history:
                    self._history.close()


class _Progress:
    """Fortschritt als Ereignis: höchstens alle 100 ms, der letzte Wert immer."""

    def __init__(self, service: PrintService, job_key: str):
        self._service = service
        self._key = job_key
        self._last_sent = None
        self._last_value: tuple[int, int] | None = None
        self._sent_value: tuple[int, int] | None = None

    def __call__(self, done: int, total: int) -> None:
        self._last_value = (done, total)
        now = time.monotonic()
        if done >= total or self._last_sent is None or now - self._last_sent >= PROGRESS_INTERVAL_S:
            self._send(done, total, now)

    def _send(self, done: int, total: int, now: float) -> None:
        self._last_sent = now
        self._sent_value = (done, total)
        self._service._emit("progress", {"job_key": self._key, "done": done, "total": total})

    def flush(self) -> None:
        if self._last_value is not None and self._last_value != self._sent_value:
            self._send(*self._last_value, time.monotonic())
