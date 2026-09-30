"""Warteschlangen-Läufer: druckt wartende Aufträge nach, sobald der Drucker erreichbar ist.

Backoff 30 s -> 5 min (`RetryScheduler`), passive Erreichbarkeits-Probe (BLE-Advertisement) statt
Port-Open, Pause bei verifiziert offenem Deckel, abschaltbar (`queue.auto_retry`), sichtbare
Wartezeit (`next_try`, `last_reason`). Pausiert automatisch, solange der Drucker reserviert ist.
`tick()` ist ein synchroner Schritt (Tests rufen ihn direkt); `start()` betreibt ihn im Thread.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from tapesmith.config import setting
from tapesmith.daemon.probe import Backoff, ReachabilityProbe, RetryDecision, RetryScheduler, make_probe
from tapesmith.daemon.queue import JobQueue, QueueClosed
from tapesmith.ipc.codec import decode_request
from tapesmith.lock import PrinterBusy
from tapesmith.transport.base import ConnectTimeout
from tapesmith.i18n import N_, _t

if TYPE_CHECKING:  # pragma: no cover
    from tapesmith.daemon.service import PrintService

log = logging.getLogger(__name__)

IDLE_WAIT_S = 30.0
MAX_WAIT_S = 30.0
BUSY_RETRY_S = 30.0

REASON_PAUSED = N_("Warteschlange pausiert")
REASON_LEASED = N_("Drucker ist für Einrichtung/Diagnose reserviert")
REASON_OFFLINE = N_("Drucker nicht erreichbar")
REASON_BUSY = N_("Drucker reserviert/belegt")
REASON_LID = N_("Deckel offen, Warteschlange pausiert")
REASON_SENSITIVE_LOST = N_("Sensibler Auftrag nach Neustart nicht mehr vorhanden, bitte neu drucken")
REASON_INCOMPLETE = N_("Druck unvollständig, im Verlauf erneut drucken")


def backoff_from_config(cfg: dict) -> Backoff:
    return Backoff(float(setting(cfg, "queue.backoff_start_s")), float(setting(cfg, "queue.backoff_max_s")))


def probe_key(cfg: dict) -> tuple:
    """Alles, was die Erreichbarkeits-Probe bestimmt (Wechsel -> neue Probe)."""
    return (str(setting(cfg, "queue.probe")), tuple(setting(cfg, "ble.names")), setting(cfg, "ble.address"))


def probe_from_config(cfg: dict) -> ReachabilityProbe:
    mode, names, address = probe_key(cfg)
    return make_probe(mode, names=names, address=address)


class QueueRunner:
    def __init__(self, service: PrintService, queue: JobQueue, scheduler: RetryScheduler,
                 probe: ReachabilityProbe, *, now: Callable[[], datetime] = datetime.now,
                 probe_factory: Callable[[dict], ReachabilityProbe] = probe_from_config):
        self._service = service
        self._queue = queue
        self._scheduler = scheduler
        self._probe = probe
        self._probe_factory = probe_factory
        cfg = getattr(service, "config", None)     # Stand, zu dem `probe` passt
        self._probe_key = probe_key(cfg) if isinstance(cfg, dict) else None
        self._now = now
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._tick_lock = threading.Lock()
        self._last_reason = ""

    # ---------- Thread ----------

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name=_t("p12d-Warteschlange"), daemon=True)
        self._thread.start()

    def stop(self, timeout_s: float = 5.0) -> bool:
        """Thread anhalten und auf ihn warten. False, wenn er nach `timeout_s` noch läuft (etwa
        mitten in einem langen Druck); er beendet sich dann nach dem laufenden Schritt selbst."""
        self._stop.set()
        self._wake.set()
        thread = self._thread
        stopped = True
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout_s)
            stopped = not thread.is_alive()
        self._thread = None
        return stopped

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._wake.clear()
            try:
                decision = self.tick()
            except QueueClosed:
                log.info("Warteschlangen-Läufer: Warteschlange geschlossen, Läufer endet")
                break
            except Exception:  # noqa: BLE001 (der Läufer darf nie sterben)
                log.exception("Warteschlangen-Läufer: Fehler")
                decision = RetryDecision("warten", IDLE_WAIT_S, "")
            if self._stop.is_set():
                break
            self._wake.wait(max(0.0, min(decision.wait_s, MAX_WAIT_S)))

    def reconfigure(self, cfg: dict) -> None:
        """Warteschlangen-Einstellungen aus der neu geladenen Config übernehmen (ohne Neustart):
        automatischer Nachdruck, Backoff und Erreichbarkeits-Probe. Wirft bei ungültigen Werten,
        ohne etwas zu ändern."""
        backoff = backoff_from_config(cfg)
        auto_retry = bool(setting(cfg, "queue.auto_retry"))
        key = probe_key(cfg)
        probe = self._probe_factory(cfg) if key != self._probe_key else None
        self._scheduler.configure(backoff=backoff, auto_retry=auto_retry)
        if probe is not None:
            self._probe = probe
            self._probe_key = key
        self._wake.set()

    @property
    def auto_retry(self) -> bool:
        return self._scheduler.auto_retry

    def wake(self, manual: bool = False) -> None:
        if manual:
            self._scheduler.on_manual_retry()
        self._wake.set()

    def notify_offline(self) -> None:
        wait = self._scheduler.on_offline()
        until = self._now() + timedelta(seconds=wait)
        for job in self._queue.list():
            if job.state == "wartet" and (job.next_try is None or job.next_try < until):
                self._queue.mark_retry(job.id, _t(REASON_OFFLINE), until)
        self._last_reason = _t("{reason_offline}, nächster Versuch in {wait} s", reason_offline=_t(REASON_OFFLINE), wait=int(round(wait)))
        self._emit_queue()

    def notify_online(self) -> None:
        """Ein Druck ist gerade gelungen: Backoff zurücksetzen, Wartende sofort versuchen."""
        self._scheduler.on_online()
        self._queue.retry_now(None)
        self._emit_queue()
        self._wake.set()

    # ---------- Anzeige ----------

    @property
    def last_reason(self) -> str:
        return self._last_reason

    @property
    def probe_name(self) -> str:
        return getattr(self._probe, "name", "none")

    def next_try(self) -> datetime | None:
        earliest = self._queue.earliest_next_try()
        if earliest is not None:
            return earliest
        rest = self._scheduler.next_try_in
        if rest is not None and self._queue.active_count() > 0:
            return self._now() + timedelta(seconds=rest)
        return None

    # ---------- ein Schritt ----------

    def _emit_queue(self) -> None:
        emit = getattr(self._service, "_emit", None)
        if emit is not None:
            emit("queue", {})

    def _wait(self, wait_s: float, reason: str) -> RetryDecision:
        self._last_reason = reason
        return RetryDecision("warten", wait_s, reason)

    def tick(self) -> RetryDecision:
        with self._tick_lock:
            return self._tick()

    def _tick(self) -> RetryDecision:
        now = self._now()
        if self._queue.paused:
            return self._wait(IDLE_WAIT_S, _t(REASON_PAUSED))
        if self._service.leased:
            return self._wait(IDLE_WAIT_S, _t(REASON_LEASED))
        if self._queue.next_due(now) is None:
            return self._wait(IDLE_WAIT_S, "")
        if not self._scheduler.ready():
            decision = self._scheduler.decide(True, None)   # ohne Probe: nur Grund und Restzeit
            return self._wait(decision.wait_s, decision.reason)
        result = self._probe.check()
        decision = self._scheduler.decide(True, result)
        if decision.action != "drucken":
            until = now + timedelta(seconds=decision.wait_s)
            for job in self._queue.list():
                if job.state == "wartet":
                    self._queue.mark_retry(job.id, decision.reason or _t(REASON_OFFLINE), until)
            self._emit_queue()
            return self._wait(decision.wait_s, decision.reason)
        return self._print_due()

    def _retry_offline(self, job_id: int) -> RetryDecision:
        wait = self._scheduler.on_offline()
        self._queue.mark_retry(job_id, _t(REASON_OFFLINE), self._now() + timedelta(seconds=wait))
        self._emit_queue()
        return self._wait(wait, _t("{reason_offline}, nächster Versuch in {wait} s", reason_offline=_t(REASON_OFFLINE), wait=int(round(wait))))

    def _retry_busy(self, job_id: int) -> RetryDecision:
        self._queue.mark_retry(job_id, _t(REASON_BUSY), self._now() + timedelta(seconds=BUSY_RETRY_S))
        self._emit_queue()
        return self._wait(BUSY_RETRY_S, _t(REASON_BUSY))

    def _lid_open(self) -> bool | None:
        """True = Deckel verifiziert offen; Offline/Busy werden durchgereicht; sonst unbekannt."""
        try:
            report = self._service.status(quick=True, force=True)
        except (ConnectTimeout, PrinterBusy):
            raise
        except Exception as exc:  # noqa: BLE001 (Statuswerte blockieren nie)
            log.info("Deckelprüfung fehlgeschlagen (%s), Druck wird trotzdem versucht", exc)
            return None
        status = getattr(report, "status", None)
        lid = status.get("lid") if status is not None else None
        return lid is not None and lid.value == "offen" and lid.verified

    def _print_due(self) -> RetryDecision:
        printed = 0
        while True:
            if self._stop.is_set() or self._queue.paused or self._service.leased:
                break
            job = self._queue.next_due(self._now())
            if job is None:
                break
            payload = self._queue.payload(job.id)
            if payload is None:
                self._queue.mark_failed(job.id, _t(REASON_SENSITIVE_LOST))
                self._emit_queue()
                continue
            try:
                lid_open = self._lid_open()
            except ConnectTimeout:
                return self._retry_offline(job.id)
            except PrinterBusy:
                return self._retry_busy(job.id)
            if lid_open:
                wait = self._scheduler.on_offline()
                self._queue.mark_retry(job.id, _t(REASON_LID), self._now() + timedelta(seconds=wait))
                self._emit_queue()
                return self._wait(wait, _t(REASON_LID))
            try:
                request = decode_request(payload["request"])
            except Exception as exc:  # noqa: BLE001
                self._queue.mark_failed(job.id, _t("Auftrag nicht lesbar: {exc}", exc=exc))
                self._emit_queue()
                continue
            self._queue.mark_running(job.id)
            self._emit_queue()
            try:
                outcome = self._service.submit(request, job_key=f"queue-{job.id}", from_queue=True)
            except ConnectTimeout:
                return self._retry_offline(job.id)
            except PrinterBusy:
                return self._retry_busy(job.id)
            except Exception as exc:  # noqa: BLE001
                log.warning("Warteschlangen-Auftrag #%s fehlgeschlagen: %s", job.id, exc)
                self._queue.mark_failed(job.id, str(exc) or type(exc).__name__)
                self._emit_queue()
                continue
            status = outcome.status
            if status == "ok":
                self._queue.mark_done(job.id, outcome.history_id)
                self._scheduler.on_online()
                printed += 1
            elif status == "unvollständig":
                self._queue.mark_failed(job.id, _t(REASON_INCOMPLETE))
            elif status in ("abgelehnt", "bestätigung_nötig"):
                self._queue.mark_failed(job.id, "; ".join(outcome.reasons) or status)
            elif status == "abgebrochen":
                self._queue.cancel(job.id)
            else:
                self._queue.mark_failed(job.id, _t("Unerwarteter Ausgang: {status}", status=status))
            self._emit_queue()
        reason = _t("{printed} Aufträge gedruckt", printed=printed)
        self._last_reason = reason
        return RetryDecision("drucken", 0.0, reason)
