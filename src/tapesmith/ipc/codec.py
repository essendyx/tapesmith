"""Druck-Datentypen <-> JSON für Protokoll v1 (verlustfrei für Kopfbilder und Metadaten)."""

from __future__ import annotations

import base64
import binascii
import dataclasses
import io
from dataclasses import dataclass
from datetime import datetime

from PIL import Image, UnidentifiedImageError

from tapesmith.connection import PrinterOffline
from tapesmith.errors import explain
from tapesmith.ipc.protocol import ProtocolError
from tapesmith.jobs import IncompletePrint, JobMeta
from tapesmith.lock import PrinterBusy
from tapesmith.pipeline import PrintLabel, PrintOutcome, PrintPlan, PrintRequest
from tapesmith.printer import PrintResult
from tapesmith.status import PrinterStatus, StatusValue
from tapesmith.templates.model import TemplateError
from tapesmith.transport.base import ConnectTimeout, TransportError
from tapesmith.i18n import _t


@dataclass(frozen=True)
class StateInfo:
    state: str                          # ConnectionState.value, z. B. "verbunden"
    transport: str | None = None        # z. B. "COM4", "ble:A4:5F:…", "file:job.bin"
    last_error: str | None = None
    leased: bool = False


@dataclass(frozen=True)
class StatusReport:
    state: StateInfo
    status: PrinterStatus | None
    checked_at: datetime | None         # naive lokale Zeit, ISO ohne Zeitzone


class RemoteError(RuntimeError):
    """Fehler des Druckdienstes, dessen Art der Client nicht kennt."""

    def __init__(self, kind: str, message: str, exit_code: int):
        super().__init__(message)
        self.kind = kind
        self.exit_code = exit_code


def _field(data: dict, name: str):
    try:
        return data[name]
    except (KeyError, TypeError) as exc:
        raise ProtocolError(_t("Pflichtfeld '{name}' fehlt", name=name)) from exc


# ---------- Bilder ----------

def png_to_b64(image: Image.Image) -> str:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def b64_to_png(text: str) -> Image.Image:
    try:
        raw = base64.b64decode(text, validate=True)
        with Image.open(io.BytesIO(raw)) as img:
            img.load()
            return img.copy()
    except (binascii.Error, ValueError, TypeError, OSError, UnidentifiedImageError) as exc:
        raise ProtocolError(_t("Ungültiges Bild in Nachricht: {exc}", exc=exc)) from exc


# ---------- Druckauftrag ----------

def encode_request(request: PrintRequest) -> dict:
    return {
        "labels": [{"head_png": png_to_b64(lbl.head),
                    "landscape_png": png_to_b64(lbl.landscape) if lbl.landscape is not None else None}
                   for lbl in request.labels],
        "meta": request.meta.to_dict(),
        "copies": request.copies,
        "chain": request.chain,
        "cut_marks": request.cut_marks,
        "confirmed": request.confirmed,
        "cut_pause_s": request.cut_pause_s,
    }


def decode_request(data: dict) -> PrintRequest:
    labels = []
    for item in _field(data, "labels"):
        landscape = item.get("landscape_png")
        labels.append(PrintLabel(b64_to_png(_field(item, "head_png")),
                                 b64_to_png(landscape) if landscape is not None else None))
    meta_data = _field(data, "meta")
    try:
        meta = JobMeta(**meta_data)
    except (TypeError, ValueError) as exc:
        raise ProtocolError(_t("Ungültige Job-Metadaten: {exc}", exc=exc)) from exc
    defaults = PrintRequest(labels=(), meta=meta)
    cut_pause = data.get("cut_pause_s", defaults.cut_pause_s)
    return PrintRequest(
        labels=tuple(labels),
        meta=meta,
        copies=int(data.get("copies", defaults.copies)),
        chain=bool(data.get("chain", defaults.chain)),
        cut_marks=bool(data.get("cut_marks", defaults.cut_marks)),
        confirmed=bool(data.get("confirmed", defaults.confirmed)),
        cut_pause_s=float(cut_pause) if cut_pause is not None else None,
    )


# ---------- Fehler ----------

def encode_error(exc: BaseException) -> dict:
    incomplete = isinstance(exc, IncompletePrint)
    return {
        "kind": type(exc).__name__,
        "message": str(exc),
        "exit_code": explain(exc).exit_code,
        "rows_sent": exc.rows_sent if incomplete else None,
        "rows_total": exc.rows_total if incomplete else None,
    }


_ERROR_CLASSES: dict[str, type[BaseException]] = {
    "PrinterOffline": PrinterOffline,
    "ConnectTimeout": ConnectTimeout,
    "PrinterBusy": PrinterBusy,
    "TransportError": TransportError,
    "TemplateError": TemplateError,
    "ValueError": ValueError,
    "ProtocolError": ProtocolError,
}


def decode_error(data: dict) -> BaseException:
    kind = str(_field(data, "kind"))
    message = str(data.get("message", ""))
    if kind == "IncompletePrint":
        return IncompletePrint(message, int(data.get("rows_sent") or 0), int(data.get("rows_total") or 0))
    cls = _ERROR_CLASSES.get(kind)
    if cls is not None:
        return cls(message)
    return RemoteError(kind, message, int(data.get("exit_code", 1)))


# ---------- Status ----------

def encode_status(status: PrinterStatus | None) -> dict | None:
    return None if status is None else status.to_dict()


def decode_status(data: dict | None) -> PrinterStatus | None:
    if data is None:
        return None
    try:
        values = {
            kind: StatusValue(kind, v["value"], v["text"], bool(v["verified"]), bytes.fromhex(v["raw"]))
            for kind, v in data.get("values", {}).items()
        }
        unknown = [bytes.fromhex(item) for item in data.get("unknown", [])]
        raw = bytes.fromhex(data.get("raw", ""))
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ProtocolError(_t("Ungültiger Druckerstatus: {exc}", exc=exc)) from exc
    return PrinterStatus(values=values, unknown=unknown, raw=raw)


def encode_state(info: StateInfo) -> dict:
    return {"state": info.state, "transport": info.transport, "last_error": info.last_error,
            "leased": info.leased}


def decode_state(data: dict) -> StateInfo:
    return StateInfo(state=str(_field(data, "state")), transport=data.get("transport"),
                     last_error=data.get("last_error"), leased=bool(data.get("leased", False)))


def encode_report(report: StatusReport) -> dict:
    checked = report.checked_at.isoformat(timespec="seconds") if report.checked_at is not None else None
    return {"state": encode_state(report.state), "status": encode_status(report.status),
            "checked_at": checked}


def decode_report(data: dict) -> StatusReport:
    checked = data.get("checked_at")
    try:
        checked_at = datetime.fromisoformat(checked) if checked is not None else None
    except (TypeError, ValueError) as exc:
        raise ProtocolError(_t("Ungültiger Zeitpunkt '{checked}'", checked=checked)) from exc
    return StatusReport(state=decode_state(_field(data, "state")), status=decode_status(data.get("status")),
                        checked_at=checked_at)


# ---------- Druckergebnis ----------

def encode_outcome(outcome: PrintOutcome) -> dict:
    return {
        "status": outcome.status,
        "warnings": list(outcome.warnings),
        "reasons": list(outcome.reasons),
        "history_id": outcome.history_id,
        "consumed_mm": outcome.consumed_mm,
        "results": [{"rows": r.rows, "rows_sent": r.rows_sent, "waited_s": r.waited_s, "status": r.status}
                    for r in outcome.results],
        "printer_status": encode_status(outcome.printer_status),
        "error": encode_error(outcome.error) if outcome.error is not None else None,
        "queue_id": getattr(outcome, "queue_id", None),
    }


def decode_outcome(data: dict, plan: PrintPlan) -> PrintOutcome:
    try:
        results = [PrintResult(int(r["rows"]), [], float(r["waited_s"]), str(r["status"]),
                               r.get("rows_sent"))
                   for r in data.get("results", [])]
    except (KeyError, TypeError, ValueError) as exc:
        raise ProtocolError(_t("Ungültiges Teilergebnis: {exc}", exc=exc)) from exc
    error = data.get("error")
    queue_id = data.get("queue_id")
    kwargs = {}
    if any(f.name == "queue_id" for f in dataclasses.fields(PrintOutcome)):
        kwargs["queue_id"] = queue_id
    outcome = PrintOutcome(
        status=str(_field(data, "status")),
        plan=plan,
        results=results,
        warnings=list(data.get("warnings", [])),
        printer_status=decode_status(data.get("printer_status")),
        history_id=data.get("history_id"),
        error=decode_error(error) if error is not None else None,
        reasons=tuple(data.get("reasons", [])),
        consumed_mm=float(data.get("consumed_mm", 0.0)),
        **kwargs,
    )
    if "queue_id" not in kwargs:
        outcome.queue_id = queue_id
    return outcome
