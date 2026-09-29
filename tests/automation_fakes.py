"""Test-Fakes für Addons und Kanäle (LAN und Automatisierung): `FakeFacade` statt echter Fassade.

Die Rückgabeformen entsprechen genau der echten `LabelFacade` (gleiche Schlüssel, gleiche
Verschachtelung); `tests/test_automation_fakes.py` belegt das gegen einen echten Dienst.
"""

from __future__ import annotations

import copy
import io
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta

from PIL import Image

import daemon_fakes
from tapesmith.jobs import SOURCES
from tapesmith.webapi.labels import LabelNotPrintable, Resolved


def _tiny_png() -> bytes:
    buf = io.BytesIO()
    Image.new("1", (1, 1), 255).save(buf, format="PNG")
    return buf.getvalue()


PNG_1X1 = _tiny_png()

DEFAULT_OUTCOME = {"status": "ok", "warnings": [], "reasons": [], "history_id": 1, "consumed_mm": 30.0,
                   "results": [], "printer_status": None, "error": None, "queue_id": None, "job_key": "k1",
                   "title": "Test", "balance_text": ""}

DEFAULT_VERIFIED = ("battery", "lid", "media", "serial", "firmware")

_LID_RAW = {"zu": "1a0598", "offen": "1a0599"}


class FakeClock(daemon_fakes.FakeClock):
    """Monotone Uhr (Sekunden) mit `advance(s)`."""

    def advance(self, seconds: float) -> float:
        self.now += seconds
        return self.now


class FakeNow(daemon_fakes.FakeNow):
    """Wanduhr (`datetime`) mit `advance(**timedelta_kw)`."""

    def advance(self, **kw) -> datetime:
        self.now = self.now + timedelta(**kw)
        return self.now


def state_json(state: str = "verbunden", transport: str | None = "COM4", last_error: str | None = None,
               leased: bool = False) -> dict:
    """Form von `codec.encode_state`."""
    return {"state": state, "transport": transport, "last_error": last_error, "leased": leased}


def status_json(battery: int | None = 75, lid: str | None = "zu", state: str = "verbunden",
                status_none: bool = False) -> dict:
    """`StatusJson` wie `webapi.convert.status_json`; `battery`/`lid` None lassen den Wert weg."""
    values: dict[str, dict] = {}
    if battery is not None:
        values["battery"] = {"value": battery, "text": f"{battery} %", "verified": True,
                             "raw": f"1a04{battery:02d}"}
    if lid is not None:
        values["lid"] = {"value": lid, "text": lid, "verified": True, "raw": _LID_RAW.get(lid, "")}
    status = None if status_none else {"answered": True, "values": values, "unknown": [], "raw": ""}
    connected = state == "verbunden"
    transport = "COM4" if connected else None
    chip = f"P12 · {state}" + (" (COM4)" if connected else "")
    if connected and battery is not None:
        chip += f" · Akku {battery} %"
    return {
        "report": {"state": state_json(state, transport), "status": status,
                   "checked_at": "2026-09-28T10:00:00"},
        "view": {"chip": chip, "role": "success" if connected else "secondary",
                 "title": f"Tapesmith · {state}", "detail": "", "tooltip": ""},
    }


def queued_job(id: int, state: str = "wartet", created: str = "2026-09-28T10:00:00", title: str = "Test",
               source: str = "api", sensitive: bool = False, last_error: str = "") -> dict:
    """Eintrag in `queue()["jobs"]` wie `daemon.queue.QueuedJob.to_dict` (Fehlerfeld `last_error`)."""
    return {"id": id, "created": created, "source": source, "title": title, "state": state,
            "position": id, "attempts": 0, "next_try": None, "last_error": last_error,
            "sensitive": sensitive, "history_id": None}


def queue_json(jobs: Sequence[dict] = ()) -> dict:
    """Form von `PrintService.queue_snapshot`."""
    return {"jobs": [dict(j) for j in jobs], "paused": False, "auto_retry": True, "next_try": None,
            "probe": "status", "waiting_reason": ""}


def field_json(id: str, label: str, *, required: bool = False, default: str | None = "",
               choices: Sequence[str] = (), max_len: int | None = None, secret: bool = False,
               multiline: bool = False, type: str = "input") -> dict:
    """Eingabefeld wie `routes_templates._field_json`."""
    return {"id": id, "label": label, "type": type, "default": default, "required": required,
            "secret": secret, "choices": list(choices), "choice_labels": {}, "max_len": max_len,
            "multiline": multiline, "role": None, "default_hint": None}


def template_summary(name: str, fields: Sequence[dict], *, description: str = "", category: str = "Haushalt",
                     tapes: Sequence[str] = (), sample: dict | None = None, favorite: bool = False) -> dict:
    """`TemplateSummary` wie `routes_templates.template_summary_json`."""
    return {"name": name, "title": name, "description": description, "category": category, "tags": [],
            "kind": "document",
            "builtin": True, "favorite": favorite, "target": None, "tapes": list(tapes),
            "default_copies": 1, "input_fields": [dict(f) for f in fields],
            "sample": dict(sample) if sample is not None else {f["id"]: f["default"] or "" for f in fields}}


def default_templates() -> list[dict]:
    return [
        template_summary("gefriergut", [
            field_json("inhalt", "Inhalt", required=True, max_len=16),
            field_json("kategorie", "Kategorie", default="Fleisch",
                       choices=["Fleisch", "Hackfleisch", "Fisch", "Gemüse", "Obst", "Brot",
                                "Fertiggericht", "Suppe"]),
        ], description="Gefriergut mit Haltbarkeit", tapes=["material:kunststoff"],
            sample={"inhalt": "Gulasch", "kategorie": "Fleisch"}),
        template_summary("eigentum", [
            field_json("name", "Name", required=True, max_len=20),
            field_json("telefon", "Telefon", max_len=16),
        ], description="Eigentumskennzeichnung für Werkzeug", sample={"name": "Max Muster", "telefon": ""}),
    ]


def default_render(title: str = "Test") -> dict:
    """`RenderJson` eines druckbaren Labels (Vorschau mit Platzhalterbildern)."""
    import base64
    png = base64.b64encode(PNG_1X1).decode("ascii")
    preview = {"design_png": png, "raster_png": png, "width": 1, "height": 1, "info": "", "content_mm": 20.0,
               "tape_mm": 30.0, "labels": 1, "jobs": 1, "estimated": False, "balance_text": "",
               "decision": {"allowed": True, "needs_confirmation": False, "reasons": []}, "warnings": []}
    return {"ok": True, "title": title, "preview": preview, "errors": [], "warnings": [], "issues": [],
            "fixes": [], "font_size": None, "qr": None, "values": None, "shortened": [], "notes": [],
            "tape_reason": None, "missing_secrets": [], "editor": None}


def _check_origin(origin: str) -> None:
    if origin not in SOURCES:
        raise ValueError(f"Unbekannte Quelle '{origin}' (erlaubt: {', '.join(SOURCES)})")


class FakeFacade:
    """Fassade ohne Dienst: liefert feste Werte und zeichnet Aufrufe auf."""

    def __init__(self, config: dict | None = None, templates: list[dict] | None = None,
                 outcome: dict | None = None, render: dict | None = None, status: dict | None = None,
                 state: dict | None = None, queue: dict | None = None, history: list[dict] | None = None,
                 verified: Sequence[str] = DEFAULT_VERIFIED, remaining_m: float | None = None,
                 preview: bytes = PNG_1X1):
        self._config = config if config is not None else {}
        self.templates = templates if templates is not None else default_templates()
        self.outcome = outcome if outcome is not None else dict(DEFAULT_OUTCOME)
        self.render_result = render if render is not None else default_render()
        self.status_value = status if status is not None else status_json()
        self.state_value = state if state is not None else state_json()
        self.queue_value = queue if queue is not None else queue_json()
        self.history_value = history if history is not None else []
        self.verified_value = tuple(verified)
        self.remaining_value = remaining_m
        self.preview = preview
        self.printed: list[tuple[dict, dict | None, str]] = []
        self.rendered: list[tuple[dict, dict | None, str]] = []
        self.previewed: list[tuple[dict, dict | None, str, bool]] = []
        self.cancelled: list[int] = []
        self.raise_on_print: Exception | None = None
        self.subscribers: list[Callable[[str, dict], None]] = []

    # ---------- Konfiguration ----------

    def config(self) -> dict:
        return self._config

    # ---------- Labels ----------

    def render(self, source: dict, options: dict | None = None, *, origin: str) -> dict:
        _check_origin(origin)
        self.rendered.append((source, options, origin))
        return copy.deepcopy(self.render_result)

    def print(self, source: dict, options: dict | None = None, *, origin: str) -> dict:
        _check_origin(origin)
        self.printed.append((source, options, origin))
        if self.raise_on_print is not None:
            raise self.raise_on_print
        return copy.deepcopy(self.outcome)

    def preview_png(self, source: dict, options: dict | None = None, *, origin: str,
                    raster: bool = False) -> bytes:
        _check_origin(origin)
        self.previewed.append((source, options, origin, raster))
        if not self.render_result.get("ok"):
            errors = list(self.render_result.get("errors") or ["Label nicht druckbar"])
            raise LabelNotPrintable(Resolved(title=self.render_result.get("title", ""), labels=(), meta=None,
                                             ok=False, errors=errors, warnings=[], issues=[], fixes=[]))
        return self.preview

    def template_summaries(self, names: Sequence[str] | None = None) -> list[dict]:
        if names is None:
            return copy.deepcopy(self.templates)
        by_name = {t["name"]: t for t in self.templates}
        return [copy.deepcopy(by_name[n]) for n in names if n in by_name]

    # ---------- Zustand ----------

    def status(self) -> dict:
        return copy.deepcopy(self.status_value)

    def state(self) -> dict:
        return dict(self.state_value)

    def queue(self, include_done: bool = False) -> dict:
        return copy.deepcopy(self.queue_value)

    def cancel_queued(self, job_id: int) -> bool:
        self.cancelled.append(job_id)
        jobs = self.queue_value.get("jobs", [])
        before = len(jobs)
        self.queue_value["jobs"] = [j for j in jobs if j.get("id") != job_id]
        return len(self.queue_value["jobs"]) < before

    def history(self, limit: int = 20, query: str = "") -> list[dict]:
        return copy.deepcopy(self.history_value[:limit])

    def remaining_m(self) -> float | None:
        return self.remaining_value

    def verified(self) -> tuple[str, ...]:
        return self.verified_value

    def subscribe(self, fn: Callable[[str, dict], None]) -> None:
        self.subscribers.append(fn)

    def emit(self, event: str, data: dict) -> None:
        for fn in list(self.subscribers):
            fn(event, data)
