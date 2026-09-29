"""Druck-Pipeline: ein Kern-Einstieg für jeden Druck (CLI und GUI).

Plant Kopien und Ketten, prüft den Fehldruckschutz, fragt vor dem Senden den
Druckerstatus ab (nur Warnen, nie blockieren), druckt mit Abbruch und ehrlichem Status
bei unvollständigen Drucken und hält jeden Ausgang im Verlauf fest. Ausführung
wahlweise direkt (eine Sitzung je Auftrag) oder über den ConnectionManager.
Der Verlaufseintrag entsteht erst, wenn die Verbindung steht.

`execute` darf aus einem Worker-Thread laufen; `CancelToken.cancel()` aus dem UI-Thread.
"""

from __future__ import annotations

import contextlib
import dataclasses
import threading
import time
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from PIL import Image

from tapesmith.connection import ConnectionManager
from tapesmith.device.profile import DeviceProfile
from tapesmith.export import export_heads, head_to_landscape
from tapesmith.guard import (
    Debouncer,
    GuardDecision,
    GuardPolicy,
    JobRequest,
    JobRunning,
    Usage,
    content_key,
    evaluate,
)
from tapesmith.history import HistoryStore
from tapesmith.jobs import CancelToken, IncompletePrint, JobMeta
from tapesmith.printer import STATUS_CANCELLED, PrinterSession, PrintResult
from tapesmith.render.chain import ChainPlan, chain_preview, expand_copies, plan_chain, plan_single
from tapesmith.render.compose import RenderResult, rows_to_mm
from tapesmith.status import PREFLIGHT_QUERIES, PrinterStatus, preflight, read_status
from tapesmith.i18n import N_, _t

RunSession = Callable[[Callable[[PrinterSession], Any]], Any]

CUT_PAUSE_OFF = -1.0      # Anfrage: ausdrücklich keine Schneidpause
CUT_PAUSE_KEY = 0.0       # warten bis continue_after_cut()

OUTCOME_STATUSES = ("ok", "abgebrochen", "unvollständig", "abgelehnt", "bestätigung_nötig", "wartet")

DOUBLE_PRESS_REASON = N_("Gleicher Druck wurde gerade eben ausgelöst, doppelt gedrückt?")
JOB_RUNNING_REASON = N_("Druckauftrag lief bereits")
QUOTA_WINDOW = timedelta(hours=1)


@dataclass(frozen=True)
class PrintLabel:
    head: Image.Image                       # Breite profile.head_dots
    landscape: Image.Image | None = None    # für Miniatur; None -> export.head_to_landscape


@dataclass(frozen=True)
class PrintRequest:
    labels: tuple[PrintLabel, ...]
    meta: JobMeta
    copies: int = 1
    chain: bool = False
    cut_marks: bool = True
    confirmed: bool = False
    cut_pause_s: float | None = None        # None = Pipeline-Standard; CUT_PAUSE_OFF; CUT_PAUSE_KEY; > 0 s


@dataclass(frozen=True)
class CheckResult:
    """Ergebnis einer Plan-Prüfung: Warnungen und Rückfragegründe (wie Überlänge)."""
    warnings: tuple[str, ...] = ()
    confirm: tuple[str, ...] = ()


@dataclass(frozen=True)
class PrintPlan:
    request: PrintRequest
    chain: ChainPlan
    decision: GuardDecision
    label_mm: float                         # längstes Label (Inhalt)
    check_warnings: tuple[str, ...] = ()

    @property
    def balance_text(self) -> str:
        return self.chain.balance.text()


@dataclass
class PrintOutcome:
    status: str
    plan: PrintPlan
    results: list[PrintResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    printer_status: PrinterStatus | None = None
    history_id: int | None = None
    error: BaseException | None = None
    reasons: tuple[str, ...] = ()
    consumed_mm: float = 0.0
    queue_id: int | None = None


PlanCheck = Callable[[PrintPlan], CheckResult]
StatusCheck = Callable[[PrintPlan, "PrinterStatus | None"], list[str]]
CutPauseCallback = Callable[[str, int, int, float], None]  # (state, fertige Jobs, Jobs gesamt, Sekunden)

CHECK_FAILED = N_("Prüfung fehlgeschlagen: {}")


def direct_runner(open_session: Callable[[], AbstractContextManager[PrinterSession]]) -> RunSession:
    def run(fn: Callable[[PrinterSession], Any]) -> Any:
        with open_session() as session:
            return fn(session)
    return run


def manager_runner(manager: ConnectionManager) -> RunSession:
    return manager.run


def labels_from_result(result: RenderResult) -> tuple[PrintLabel, ...]:
    return (PrintLabel(result.head, result.landscape),)


class PrintPipeline:
    def __init__(self, profile: DeviceProfile, run_session: RunSession, *,
                 history: HistoryStore | None = None,
                 policy: GuardPolicy | None = None,
                 debouncer: Debouncer | None = None,
                 preflight: bool = True,
                 on_warning: Callable[[str], None] | None = None,
                 now: Callable[[], datetime] = datetime.now,
                 checks: Sequence[PlanCheck] = (),
                 status_checks: Sequence[StatusCheck] = (),
                 on_consumed: Callable[[float], None] | None = None,
                 on_cut_pause: CutPauseCallback | None = None,
                 cut_pause_s: float | None = None,
                 clock: Callable[[], float] = time.monotonic,
                 pause_poll_s: float = 0.05):
        self.profile = profile
        self._run_session = run_session
        self._history = history
        self._policy = policy
        self._debouncer = debouncer
        self._preflight = preflight
        self._on_warning = on_warning or (lambda _w: None)
        self._now = now
        self._checks: list[PlanCheck] = list(checks)
        self._status_checks: list[StatusCheck] = list(status_checks)
        self._on_consumed = on_consumed
        self._on_cut_pause = on_cut_pause
        self._cut_pause_s = cut_pause_s
        self._clock = clock
        self._pause_poll_s = pause_poll_s
        self._continue = threading.Event()
        self._pausing = False

    # ---------- Laufzeit-Einstellungen ----------

    def set_policy(self, policy: GuardPolicy | None) -> None:
        self._policy = policy

    def set_profile(self, profile: DeviceProfile) -> None:
        self.profile = profile

    def add_check(self, check: PlanCheck) -> None:
        self._checks.append(check)

    def add_status_check(self, check: StatusCheck) -> None:
        self._status_checks.append(check)

    def set_cut_pause(self, seconds: float | None) -> None:
        """Standard-Schneidpause für Anfragen mit `cut_pause_s=None`."""
        self._cut_pause_s = seconds

    @property
    def cut_pause_active(self) -> bool:
        return self._pausing

    def continue_after_cut(self) -> bool:
        """Beendet eine laufende Schneidpause. True, wenn gerade eine Pause lief."""
        was = self._pausing
        self._continue.set()
        return was

    # ---------- Planung ----------

    def plan(self, request: PrintRequest) -> PrintPlan:
        if not request.labels:
            raise ValueError(_t("Keine Labels zum Drucken"))
        if request.copies < 1:
            raise ValueError(_t("Kopien müssen ≥ 1 sein"))
        heads = expand_copies([lbl.head for lbl in request.labels], request.copies)
        if request.chain:
            chain = plan_chain(heads, self.profile, cut_marks=request.cut_marks)
        else:
            chain = plan_single(heads, self.profile)
        label_mm = max(rows_to_mm(lbl.head.height, self.profile) for lbl in request.labels)
        meta = request.meta
        if self._history is not None:
            usage = Usage(*self._history.usage_since(meta.source, self._now() - QUOTA_WINDOW))
        else:
            usage = Usage()
        decision = evaluate(
            JobRequest(source=meta.source, label_mm=label_mm, tape_mm=chain.balance.chain_mm,
                       copies=request.copies, labels=len(request.labels)),
            self._policy, usage)
        plan = PrintPlan(request=request, chain=chain, decision=decision, label_mm=label_mm)
        return self._apply_checks(plan)

    def _apply_checks(self, plan: PrintPlan) -> PrintPlan:
        if not self._checks:
            return plan
        warnings: list[str] = []
        confirm: list[str] = []
        for check in list(self._checks):
            try:
                result = check(plan)
            except Exception as exc:
                warnings.append(_t(CHECK_FAILED).format(exc))
                continue
            if result is None:
                continue
            warnings.extend(result.warnings)
            confirm.extend(result.confirm)
        decision = plan.decision
        if confirm and decision.allowed:
            decision = GuardDecision(allowed=True, needs_confirmation=True,
                                     reasons=tuple(decision.reasons) + tuple(confirm))
        return dataclasses.replace(plan, decision=decision, check_warnings=tuple(warnings))

    def export(self, plan: PrintPlan, path: Path, fmt: str | None = None, **kw) -> Path:
        return export_heads(path, [job.head for job in plan.chain.jobs], self.profile, fmt=fmt, **kw)

    def preview(self, plan: PrintPlan, scale: int = 2) -> Image.Image:
        return chain_preview(plan.chain, self.profile, scale=scale)

    # ---------- Ausführung ----------

    def _warn(self, warnings: list[str], text: str) -> None:
        warnings.append(text)
        self._on_warning(text)

    def _set_history(self, history_id: int | None, status: str, error: str = "") -> None:
        if self._history is not None and history_id is not None:
            self._history.update_status(history_id, status, error)

    def _record(self, plan: PrintPlan) -> int | None:
        if self._history is None:
            return None
        request = plan.request
        first = request.labels[0]
        landscape = first.landscape if first.landscape is not None else head_to_landscape(
            first.head, self.profile)
        # Nur das Originalbild des ersten Labels; Kopien/Kette stecken in copies/chained.
        return self._history.record(
            request.meta, landscape=landscape, head=first.head,
            length_mm=sum(rows_to_mm(job.head.height, self.profile) for job in plan.chain.jobs),
            tape_mm=plan.chain.balance.chain_mm, copies=request.copies,
            chained=plan.chain.chained, status="läuft")

    def _run_status_checks(self, plan: PrintPlan, status: PrinterStatus | None,
                           warnings: list[str]) -> None:
        for check in list(self._status_checks):
            try:
                texts = check(plan, status) or []
            except Exception as exc:
                texts = [_t(CHECK_FAILED).format(exc)]
            for text in texts:
                self._warn(warnings, text)

    def _job_mm(self, rows_sent: int) -> float:
        profile = self.profile
        return rows_to_mm(rows_sent, profile) + profile.leader_mm + profile.trailer_mm

    def _report_consumed(self, outcome: PrintOutcome, extra_rows: int = 0) -> None:
        mm = sum(self._job_mm(r.rows_sent) for r in outcome.results if r.rows_sent)
        if extra_rows > 0:
            mm += self._job_mm(extra_rows)
        outcome.consumed_mm = mm
        if mm > 0 and self._on_consumed is not None:
            try:
                self._on_consumed(mm)
            except Exception as exc:
                self._warn(outcome.warnings, _t("Bandverbrauch nicht erfasst: {exc}", exc=exc))

    def _pause_seconds(self, request: PrintRequest) -> float | None:
        seconds = request.cut_pause_s if request.cut_pause_s is not None else self._cut_pause_s
        if seconds is None or seconds < 0:
            return None
        return float(seconds)

    def _notify_cut_pause(self, state: str, done: int, total: int, seconds: float) -> None:
        if self._on_cut_pause is None:
            return
        try:
            self._on_cut_pause(state, done, total, seconds)
        except Exception:
            pass  # Anzeige der Pause darf den Druck nie stören

    def _cut_pause(self, done: int, total: int, seconds: float, cancel: CancelToken | None) -> None:
        """Schneidpause nach Job `done`: wartet auf „Weiter“, Abbruch oder Zeitablauf.
        Läuft innerhalb der Sitzung; Verbindung und Job-Sperre bleiben gehalten."""
        self._continue.clear()
        self._pausing = True
        try:
            self._notify_cut_pause("start", done, total, seconds)
            deadline = self._clock() + seconds if seconds > 0 else None
            while not self._continue.is_set():
                if cancel is not None and cancel.cancelled:
                    break
                if deadline is not None and self._clock() >= deadline:
                    break
                self._continue.wait(self._pause_poll_s)
        finally:
            self._pausing = False
            self._notify_cut_pause("end", done, total, seconds)

    def execute(self, request: PrintRequest, *, cancel: CancelToken | None = None,
                on_progress: Callable[[int, int], None] | None = None,
                debounce: bool = True) -> PrintOutcome:
        plan = self.plan(request)
        warnings = list(plan.chain.warnings) + list(plan.check_warnings)
        decision = plan.decision

        if not decision.allowed:
            return PrintOutcome("abgelehnt", plan, warnings=warnings, reasons=decision.reasons)
        if decision.needs_confirmation and not request.confirmed:
            return PrintOutcome("bestätigung_nötig", plan, warnings=warnings, reasons=decision.reasons)
        if debounce and self._debouncer is not None:
            key = content_key(request.meta.source, [job.head for job in plan.chain.jobs])
            if not self._debouncer.accept(key):
                return PrintOutcome("abgelehnt", plan, warnings=warnings,
                                    reasons=(_t(DOUBLE_PRESS_REASON),))

        for text in warnings:
            self._on_warning(text)

        outcome = PrintOutcome("ok", plan, warnings=warnings)
        jobs = plan.chain.jobs
        total_rows = sum(job.head.height for job in jobs)
        profile = self.profile
        pause_s = self._pause_seconds(request)

        def fn(session: PrinterSession) -> None:
            outcome.history_id = self._record(plan)
            if self._preflight and getattr(session.transport, "supports_responses", True):
                status = read_status(session, profile, PREFLIGHT_QUERIES)
                outcome.printer_status = status
                for text in preflight(status, profile):
                    self._warn(warnings, text)
            self._run_status_checks(plan, outcome.printer_status, warnings)
            done_before = 0
            for i, job in enumerate(jobs):
                if cancel is not None and cancel.cancelled:
                    outcome.status = "abgebrochen"
                    break
                progress = None
                if on_progress is not None:
                    offset = done_before

                    def progress(done: int, _total: int, _offset: int = offset) -> None:
                        on_progress(_offset + done, total_rows)
                result = session.print_image(job.head, cancel=cancel, on_progress=progress)
                outcome.results.append(result)
                done_before += job.head.height
                if result.status == STATUS_CANCELLED:
                    outcome.status = "abgebrochen"
                    break
                # print_image hat die Druckzeit bereits abgewartet: die Pause beginnt danach.
                if pause_s is not None and i < len(jobs) - 1:
                    self._cut_pause(i + 1, len(jobs), pause_s, cancel)

        guard_ctx = self._debouncer.running() if self._debouncer is not None else contextlib.nullcontext()
        try:
            with guard_ctx:
                self._run_session(fn)
        except JobRunning:
            # Debouncer lehnt ab, bevor `fn` (und damit `_record`) lief -> kein Verlaufseintrag.
            outcome.status = "abgelehnt"
            outcome.reasons = (_t(JOB_RUNNING_REASON),)
            return outcome
        except IncompletePrint as exc:
            self._set_history(outcome.history_id, "unvollständig", str(exc))
            outcome.status = "unvollständig"
            outcome.error = exc
            self._report_consumed(outcome, exc.rows_sent)
            return outcome
        except BaseException as exc:
            # Scheitert die Verbindung, bevor `fn` lief, ist history_id noch None -> kein Eintrag.
            self._set_history(outcome.history_id, "fehler", str(exc))
            raise

        self._set_history(outcome.history_id, outcome.status)
        self._report_consumed(outcome)
        return outcome
