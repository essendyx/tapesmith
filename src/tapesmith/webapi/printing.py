"""Druck-Helfer der Web-API: Druckoptionen prüfen, Auftrag bauen, über den Dienst drucken.

Gedruckt wird immer über `PrintService.submit` (dieselbe Pipeline wie Pipe-Clients). Ausnahmen
des Dienstes (`PrinterBusy`, `ConnectTimeout` …) werden hier bewusst nicht gefangen: die
Fehlerabbildung (`webapi.errors`) macht daraus 409/503.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from tapesmith.config import setting
from tapesmith.ipc.codec import encode_outcome
from tapesmith.jobs import JobMeta
from tapesmith.pipeline import CUT_PAUSE_OFF, PrintLabel, PrintOutcome, PrintPlan, PrintRequest
from tapesmith.i18n import N_, _t

if TYPE_CHECKING:  # pragma: no cover
    from tapesmith.webapi.context import ApiContext

log = logging.getLogger(__name__)

_JOB_KEY = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
ON_DONE_FAILED = N_("Nacharbeit nach dem Druck fehlgeschlagen: {}")


@dataclass(frozen=True)
class PrintOptionsModel:
    copies: int = 1
    chain: bool = False
    cut_marks: bool = True
    confirmed: bool = False
    cut_pause_s: float | None = None
    job_key: str | None = None
    enqueue_on_offline: bool = True


_BOOL_FIELDS = ("chain", "cut_marks", "confirmed", "enqueue_on_offline")


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def options_from_json(data: dict | None) -> PrintOptionsModel:
    """`PrintOptions` aus JSON; fehlende Felder mit Standardwerten, Wertebereiche geprüft."""
    if data is None:
        return PrintOptionsModel()
    if not isinstance(data, dict):
        raise ValueError(_t("Druckoptionen müssen ein Objekt sein"))
    defaults = PrintOptionsModel()
    copies = data.get("copies", defaults.copies)
    if not (isinstance(copies, int) and not isinstance(copies, bool)) or copies < 1:
        raise ValueError(_t("Kopien müssen eine ganze Zahl ab 1 sein, nicht {copies!r}", copies=copies))
    flags = {}
    for name in _BOOL_FIELDS:
        value = data.get(name, getattr(defaults, name))
        if not isinstance(value, bool):
            raise ValueError(_t("Druckoption ‚{name}‘ muss true oder false sein, nicht {value!r}", name=name, value=value))
        flags[name] = value
    cut_pause = data.get("cut_pause_s")
    if cut_pause is not None and (not _is_number(cut_pause) or cut_pause < -1):
        raise ValueError(_t("Schneidpause muss leer, -1, 0 oder eine positive Zahl sein, nicht {cut_pause!r}", cut_pause=cut_pause))
    job_key = data.get("job_key")
    if job_key is not None and (not isinstance(job_key, str) or not _JOB_KEY.match(job_key)):
        raise ValueError(_t("Auftragsschlüssel: höchstens 64 Zeichen aus Buchstaben, Ziffern, _ und -"))
    return PrintOptionsModel(copies=copies, cut_pause_s=float(cut_pause) if cut_pause is not None else None,
                             job_key=job_key, **flags)


def build_request(labels: Sequence[PrintLabel], meta: JobMeta, opts: PrintOptionsModel) -> PrintRequest:
    cut_pause = opts.cut_pause_s
    if cut_pause is not None and cut_pause < 0:
        cut_pause = CUT_PAUSE_OFF
    return PrintRequest(labels=tuple(labels), meta=meta, copies=opts.copies, chain=opts.chain,
                        cut_marks=opts.cut_marks, confirmed=opts.confirmed, cut_pause_s=cut_pause)


def plan_labels(ctx: ApiContext, labels: Sequence[PrintLabel], meta: JobMeta,
                opts: PrintOptionsModel) -> PrintPlan:
    return ctx.service.pipeline.plan(build_request(labels, meta, opts))


def outcome_json(outcome: PrintOutcome, *, job_key: str) -> dict:
    data = encode_outcome(outcome)
    data["job_key"] = job_key
    data["title"] = outcome.plan.request.meta.title
    data["balance_text"] = outcome.plan.balance_text
    return data


def submit_labels(ctx: ApiContext, labels: Sequence[PrintLabel], meta: JobMeta, opts: PrintOptionsModel, *,
                  on_done: Callable[[PrintOutcome], None] | None = None) -> dict:
    """Druckt über den Dienst; `on_done` nur bei `ok`/`wartet` (z. B. Zähler weiterzählen)."""
    job_key = opts.job_key or uuid.uuid4().hex
    request = build_request(labels, meta, opts)
    enqueue = bool(opts.enqueue_on_offline and setting(ctx.config(), "queue.enabled"))
    outcome = ctx.service.submit(request, job_key=job_key, enqueue_on_offline=enqueue)
    if on_done is not None and outcome.status in ("ok", "wartet"):
        try:
            on_done(outcome)
        except Exception as exc:  # noqa: BLE001 (der Druck ist gelaufen, nur Warnung)
            log.warning("Nacharbeit nach Druck %s fehlgeschlagen: %s", job_key, exc)
            outcome.warnings.append(_t(ON_DONE_FAILED).format(exc))
    return outcome_json(outcome, job_key=job_key)
