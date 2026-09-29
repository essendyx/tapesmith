"""Fakes für GUI-Tests: Druck-Backend mit Listener-Registry, aufgezeichneten
Aufrufen und `QueueOps`, dazu eine manuell auslösbare Timer-Attrappe. Nie echte Pipes/Ports."""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from PySide6.QtCore import QObject, Signal

from tapesmith.daemon.queue import QueuedJob
from tapesmith.ipc.backend import EVENTS, QueueSnapshot
from tapesmith.ipc.codec import StateInfo, StatusReport
from tapesmith.pipeline import PrintOutcome, PrintPlan, PrintRequest
from tapesmith.status import PrinterStatus, StatusValue


def printer_status(battery: int = 75, *, verified: bool = True) -> PrinterStatus:
    value = StatusValue("battery", battery, f"Akku {battery} %", verified, b"\x1a\x04" + bytes([battery]))
    return PrinterStatus(values={"battery": value}, unknown=[], raw=value.raw)


class FakeQueueOps:
    def __init__(self, jobs=(), *, paused=False, auto_retry=True, next_try=None, probe="ble",
                 waiting_reason=""):
        self.jobs = list(jobs)
        self.paused = paused
        self.auto_retry = auto_retry
        self.next_try = next_try
        self.probe = probe
        self.waiting_reason = waiting_reason
        self.calls: list[tuple] = []
        self.fail: BaseException | None = None
        self.next_id = 100

    def list(self, include_done: bool = False) -> QueueSnapshot:
        self.calls.append(("list", include_done))
        if self.fail is not None:
            raise self.fail
        return QueueSnapshot(jobs=tuple(self.jobs), paused=self.paused, auto_retry=self.auto_retry,
                             next_try=self.next_try, probe=self.probe,
                             waiting_reason=self.waiting_reason)

    def cancel(self, job_id: int) -> bool:
        self.calls.append(("cancel", job_id))
        before = len(self.jobs)
        self.jobs = [j for j in self.jobs if j.id != job_id]
        return len(self.jobs) != before

    def duplicate(self, job_id: int) -> int:
        self.calls.append(("duplicate", job_id))
        src = next(j for j in self.jobs if j.id == job_id)
        new_id = self.next_id
        self.next_id += 1
        self.jobs.append(QueuedJob(**{**src.__dict__, "id": new_id, "position": len(self.jobs),
                                      "attempts": 0}))
        return new_id

    def move(self, job_id: int, position: int) -> None:
        self.calls.append(("move", job_id, position))
        job = next(j for j in self.jobs if j.id == job_id)
        self.jobs.remove(job)
        self.jobs.insert(position, job)

    def retry(self, job_id: int | None = None) -> None:
        self.calls.append(("retry", job_id))

    def pause(self) -> None:
        self.calls.append(("pause",))
        self.paused = True

    def resume(self) -> None:
        self.calls.append(("resume",))
        self.paused = False


def queued_job(job_id: int, *, title="Kabel", source="gui", state="wartet", position=0, attempts=0,
               next_try: datetime | None = None, last_error="", sensitive=False) -> QueuedJob:
    return QueuedJob(id=job_id, created=datetime(2026, 9, 27, 10, 0, 0), source=source, title=title,
                     state=state, position=position, attempts=attempts, next_try=next_try,
                     last_error=last_error, sensitive=sensitive, history_id=None)


@dataclass
class FakeBackend:
    """Backend-Attrappe: zeichnet Aufrufe auf, verteilt Ereignisse über `emit`."""

    kind: str = "local"
    fallback_reason: str = ""
    queue: FakeQueueOps | None = None
    state: StateInfo = field(default_factory=lambda: StateInfo("getrennt"))
    report: StatusReport | None = None
    execute_fn: Callable[..., PrintOutcome] | None = None
    calls: list = field(default_factory=list)
    listeners: dict = field(default_factory=lambda: {name: [] for name in EVENTS})
    lease_log: list = field(default_factory=list)
    reloads: int = 0
    closed: bool = False
    reload_error: BaseException | None = None
    status_error: BaseException | None = None

    def __post_init__(self) -> None:
        self._lock = threading.Lock()

    def _record(self, *call) -> None:
        with self._lock:
            self.calls.append(call)

    def names(self) -> list[str]:
        with self._lock:
            return [c[0] for c in self.calls]

    def plan(self, request: PrintRequest) -> PrintPlan:
        raise NotImplementedError

    def execute(self, request, *, cancel=None, on_progress=None, on_warning=None, on_cut_pause=None,
                enqueue_on_offline=False) -> PrintOutcome:
        self._record("execute", request, {"enqueue_on_offline": enqueue_on_offline,
                                          "on_cut_pause": on_cut_pause})
        return self.execute_fn(request, cancel=cancel, on_progress=on_progress, on_warning=on_warning)

    def continue_cut(self) -> bool:
        self._record("continue_cut")
        return True

    def preconnect(self) -> None:
        self._record("preconnect")

    def disconnect(self) -> None:
        self._record("disconnect")

    def state_info(self) -> StateInfo:
        return self.state

    def query_status(self, *, quick: bool = False, fresh: bool = True) -> StatusReport:
        self._record("query_status", {"quick": quick, "fresh": fresh})
        if self.status_error is not None:
            raise self.status_error
        report = self.report or StatusReport(self.state, printer_status(), datetime(2026, 9, 27, 12, 0))
        return report

    @contextlib.contextmanager
    def lease(self, timeout_s: float = 120.0):
        self.lease_log.append("enter")
        try:
            yield
        finally:
            self.lease_log.append("exit")

    def reload(self) -> None:
        self.reloads += 1
        self._record("reload")
        if self.reload_error is not None:
            raise self.reload_error

    def add_listener(self, event: str, callback) -> None:
        self.listeners[event].append(callback)

    def remove_listener(self, event: str, callback) -> None:
        if callback in self.listeners.get(event, []):
            self.listeners[event].remove(callback)

    def emit(self, event: str, payload) -> None:
        for callback in list(self.listeners[event]):
            callback(payload)

    def queue_ops(self):
        return self.queue

    def close(self) -> None:
        self.closed = True


class FakeTimer(QObject):
    """Timer-Attrappe für das Status-Polling: läuft nie von selbst, `fire()` löst aus."""

    timeout = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._interval = 0
        self._active = False

    def setInterval(self, ms: int) -> None:   # noqa: N802 (Qt-Schnittstelle)
        self._interval = int(ms)

    def interval(self) -> int:
        return self._interval

    def start(self, ms: int | None = None) -> None:
        if ms is not None:
            self._interval = int(ms)
        self._active = True

    def stop(self) -> None:
        self._active = False

    def isActive(self) -> bool:   # noqa: N802
        return self._active

    def fire(self) -> None:
        self.timeout.emit()
