"""Fassade `LabelFacade`: ein schmaler, stabiler Zugang zum Druckdienst für Addons.

Hotfolder, MQTT, Telegram und MCP drucken nur über diese Klasse. Sie nutzt denselben Weg wie die
Web-API (`webapi.labels`), damit Vorschau = Druck gilt und Fehldruckschutz, Kontingente, Verlauf,
Warteschlange und Restmeter überall gleich wirken. Jede Druck- und Vorschau-Methode verlangt die
Quelle des Auftrags (`origin`, einer aus `jobs.SOURCES`).
"""

from __future__ import annotations

import base64
import re
from collections.abc import Callable, Sequence
from pathlib import Path

from tapesmith import config as config_mod
from tapesmith.ipc import codec, pipe
from tapesmith.jobs import SOURCES
from tapesmith.templates import store
from tapesmith.templates.model import TemplateError
from tapesmith.webapi import convert, datajson, labels
from tapesmith.webapi.context import ApiContext
from tapesmith.webapi.events import EventBroker
from tapesmith.webapi.labels import LabelNotPrintable
from tapesmith.webapi.printing import options_from_json
from tapesmith.webapi.routes_templates import template_summary_json
from tapesmith.i18n import _t

__all__ = ["LabelFacade", "LabelNotPrintable"]

# Nur reine Vorlagennamen (wie `routes_templates._find_or_404`): nie Pfade laden.
_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def _check_origin(origin: str) -> str:
    if origin not in SOURCES:
        raise ValueError(_t("Unbekannte Quelle '{origin}' (erlaubt: {items})", origin=origin, items=', '.join(SOURCES)))
    return origin


class LabelFacade:
    """Zugang der Addons zum Druckdienst (drucken, Vorschau, Status, Warteschlange, Verlauf)."""

    def __init__(self, service, *, ctx: ApiContext | None = None):
        if ctx is None:
            ctx = ApiContext(service=service, home_key=pipe.home_key(), token="", broker=EventBroker(),
                             static_dir=Path("."), port=0)
        self.service = service
        self.ctx = ctx

    @classmethod
    def from_ctx(cls, ctx: ApiContext) -> LabelFacade:
        return cls(ctx.service, ctx=ctx)

    # ---------- Konfiguration ----------

    def config(self) -> dict:
        """Aktuelle Konfiguration (bei jedem Aufruf frisch)."""
        return self.ctx.config()

    # ---------- Labels ----------

    def render(self, source: dict, options: dict | None = None, *, origin: str) -> dict:
        """`RenderJson` (Vorschau nur bei druckbaren Labels)."""
        _check_origin(origin)
        opts = options_from_json(options)
        return labels.render_json(self.ctx, labels.resolve(self.ctx, source, origin=origin), opts)

    def print(self, source: dict, options: dict | None = None, *, origin: str) -> dict:
        """`OutcomeJson`; `LabelNotPrintable` (ValueError), wenn die Quelle nicht druckbar ist."""
        _check_origin(origin)
        return labels.print_source(self.ctx, source, options_from_json(options), origin=origin)

    def preview_png(self, source: dict, options: dict | None = None, *, origin: str,
                    raster: bool = False) -> bytes:
        """PNG der Vorschau (`design_png`, mit `raster=True` das 1-Bit-Rasterbild)."""
        _check_origin(origin)
        opts = options_from_json(options)
        resolved = labels.resolve(self.ctx, source, origin=origin)
        out = labels.render_json(self.ctx, resolved, opts)
        preview = out.get("preview")
        if not out.get("ok") or not preview:
            raise LabelNotPrintable(resolved)
        return base64.b64decode(preview["raster_png" if raster else "design_png"])

    def template_summaries(self, names: Sequence[str] | None = None) -> list[dict]:
        """`TemplateSummary` aller Vorlagen oder der genannten (in dieser Reihenfolge, Unbekannte fehlen)."""
        favs = set(config_mod.gui_setting(self.config(), "favorites"))
        if names is None:
            return [template_summary_json(t, favs) for t in store.list_templates()]
        out: list[dict] = []
        for name in names:
            if not isinstance(name, str) or not _NAME_RE.match(name):
                continue
            try:
                template = store.find_template(name)
            except TemplateError:
                continue
            out.append(template_summary_json(template, favs))
        return out

    # ---------- Zustand ----------

    def status(self) -> dict:
        """`StatusJson` aus dem Cache des Dienstes (kein Druckerkontakt)."""
        report = self.service.status(fresh=False)
        return convert.status_json(report, now=self.ctx.now(), mac=self.config().get("mac"))

    def state(self) -> dict:
        return codec.encode_state(self.service.state())

    def queue(self, include_done: bool = False) -> dict:
        return self.service.queue_snapshot(include_done=include_done)

    def cancel_queued(self, job_id: int) -> bool:
        return bool(self.service.queue_cancel(job_id))

    def history(self, limit: int = 20, query: str = "") -> list[dict]:
        history = self.service.history
        return [datajson.history_entry_json(e, history) for e in history.search(query, limit)]

    def remaining_m(self) -> float | None:
        remaining = self.service.rolls.remaining_mm()
        return None if remaining is None else remaining / 1000

    def verified(self) -> tuple[str, ...]:
        return tuple(self.ctx.profile().verified)

    def subscribe(self, fn: Callable[[str, dict], None]) -> None:
        """Ereignisse des Dienstes (`job`, `status`, `queue` …) an `fn(event, data)`."""
        self.service.add_emitter(fn)
