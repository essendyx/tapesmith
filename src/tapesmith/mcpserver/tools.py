"""Logik der MCP-Werkzeuge ohne SDK-Abhängigkeit.

Gedruckt wird nur in zwei Schritten: `label_preview` rendert, plant mit Quelle `mcp` und merkt
sich Quelle, Optionen und einen Fingerabdruck des Rasterbilds unter einer `preview_id`.
`label_print(preview_id, confirm=True)` rendert neu, vergleicht den Fingerabdruck und druckt erst
dann, mit `confirmed: true` (das bestätigt bei nicht-interaktiven Quellen nur die Band-Rückfrage). Ohne
`confirm` genau gleich `True` wird nie gedruckt.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import threading
import time
from collections import OrderedDict
from collections.abc import Callable

from tapesmith.mcpserver.backends import McpBackend
from tapesmith.i18n import N_, _t

MAX_TEXT_LINES = 3
MAX_HISTORY = 100

MSG_NOT_CONFIRMED = (N_("Nicht gedruckt: bitte die Vorschau dem Nutzer zeigen und nur nach seiner ausdrücklichen Zustimmung mit confirm=true erneut aufrufen."))
MSG_UNKNOWN = N_("Vorschau unbekannt oder abgelaufen: bitte label_preview neu aufrufen.")
MSG_STALE = (N_("Vorschau veraltet: das Label sieht inzwischen anders aus (z. B. Datum oder Zähler). Bitte label_preview neu aufrufen und die neue Vorschau zeigen."))
MSG_STALE_BROKEN = N_("Vorschau veraltet: das Label ist nicht mehr druckbar. Bitte label_preview neu aufrufen.")


class PreviewCache:
    """Bestätigbare Vorschauen: `preview_id` -> (Quelle, Optionen, Digest), mit Ablauf und Obergrenze."""

    def __init__(self, *, ttl_s: float = 900.0, max_entries: int = 50, clock: Callable[[], float] = time.monotonic):
        self.ttl_s = float(ttl_s)
        self.max_entries = int(max_entries)
        self._clock = clock
        self._entries: OrderedDict[str, tuple[float, dict, dict, str]] = OrderedDict()
        self._lock = threading.Lock()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def _expire(self, now: float) -> None:
        for key in [k for k, (born, *_rest) in self._entries.items() if now - born >= self.ttl_s]:
            del self._entries[key]

    def put(self, source: dict, options: dict, digest: str) -> str:
        with self._lock:
            now = self._clock()
            self._expire(now)
            preview_id = secrets.token_hex(8)
            while preview_id in self._entries:  # pragma: no cover: Zufallskollision
                preview_id = secrets.token_hex(8)
            self._entries[preview_id] = (now, dict(source), dict(options), digest)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)
            return preview_id

    def get(self, preview_id: str) -> tuple[dict, dict, str] | None:
        with self._lock:
            self._expire(self._clock())
            entry = self._entries.get(preview_id) if isinstance(preview_id, str) else None
            if entry is None:
                return None
            _born, source, options, digest = entry
            return dict(source), dict(options), digest

    def pop(self, preview_id: str) -> tuple[dict, dict, str] | None:
        with self._lock:
            entry = self._entries.pop(preview_id, None) if isinstance(preview_id, str) else None
            if entry is None:
                return None
            _born, source, options, digest = entry
            return dict(source), dict(options), digest


def _unique(items) -> list[str]:
    out: list[str] = []
    for item in items:
        text = str(item)
        if text and text not in out:
            out.append(text)
    return out


def _copies_message(limit: int) -> str:
    # gleicher Wortlaut wie sourcelimits.copies_error(cfg, "mcp", …)
    return _t("Kopien müssen eine ganze Zahl von 1 bis {limit} sein (Grenze für Quelle mcp: guard.confirm_copies)", limit=limit)


def _field(field: dict) -> dict:
    secret = bool(field.get("secret"))
    return {"id": field.get("id"), "label": field.get("label"), "type": field.get("type"),
            "required": bool(field.get("required")), "choices": list(field.get("choices") or []),
            "default": None if secret else field.get("default")}


def _b64(data: str | None) -> bytes | None:
    if not data:
        return None
    try:
        return base64.b64decode(data)
    except (ValueError, TypeError):
        return None


def _digest(render: dict) -> str | None:
    preview = render.get("preview") or {}
    raster = _b64(preview.get("raster_png"))
    return None if raster is None else hashlib.sha256(raster).hexdigest()


class P12Tools:
    """Die sechs Werkzeuge als reine Python-Methoden."""

    def __init__(self, backend: McpBackend, cache: PreviewCache | None = None):
        self.backend = backend
        self.cache = cache if cache is not None else PreviewCache()

    # ---------- Vorlagen ----------

    def list_templates(self, query: str = "") -> list[dict]:
        needle = str(query or "").strip().lower()
        out: list[dict] = []
        for t in self.backend.templates():
            haystack = " ".join([str(t.get("name") or ""), str(t.get("description") or ""),
                                 str(t.get("category") or ""), *[str(x) for x in t.get("tags") or []]]).lower()
            if needle and needle not in haystack:
                continue
            out.append({"name": t.get("name"), "description": t.get("description") or "",
                        "category": t.get("category") or "",
                        "fields": [_field(f) for f in t.get("input_fields") or []]})
        return out

    # ---------- Vorschau ----------

    def _source(self, template, values, text) -> dict:
        if (template is None) == (text is None):
            raise ValueError(_t("Genau eins angeben: template (Vorlagenname) oder text (1 bis 3 Zeilen)"))
        if template is not None:
            if not isinstance(template, str) or not template.strip():
                raise ValueError(_t("template muss ein Vorlagenname sein"))
            if values is None:
                values = {}
            if not isinstance(values, dict) or not all(isinstance(k, str) and isinstance(v, str)
                                                       for k, v in values.items()):
                raise ValueError(_t("values muss ein Objekt mit Texten sein (Feld-ID: Wert)"))
            return {"kind": "template", "template": template.strip(), "values": dict(values)}
        if values:
            raise ValueError(_t("values gibt es nur zusammen mit template"))
        if not isinstance(text, list) or not all(isinstance(line, str) for line in text):
            raise ValueError(_t("text muss eine Liste von Zeilen (Texten) sein"))
        if not 1 <= len(text) <= MAX_TEXT_LINES:
            raise ValueError(_t("text braucht 1 bis {max_text_lines} Zeilen, nicht {count}", max_text_lines=MAX_TEXT_LINES, count=len(text)))
        return {"kind": "text", "lines": list(text)}

    def _check_copies(self, copies) -> int:
        limit = int(self.backend.copy_limit())
        if not (isinstance(copies, int) and not isinstance(copies, bool) and 1 <= copies <= limit):
            raise ValueError(_copies_message(limit))
        return copies

    def _limits_text(self) -> str:
        getter = getattr(self.backend, "limits_text", None)
        if callable(getter):
            return getter()
        return _t("höchstens {copy_limit} Kopien je Auftrag", copy_limit=int(self.backend.copy_limit()))

    def label_preview(self, template: str | None = None, values: dict[str, str] | None = None,
                      text: list[str] | None = None, copies: int = 1) -> tuple[dict, bytes | None]:
        source = self._source(template, values, text)
        copies = self._check_copies(copies)
        options = {"copies": copies}
        render = self.backend.render(source, options)
        preview = render.get("preview")
        warnings = _unique([*(render.get("warnings") or []), *((preview or {}).get("warnings") or [])])
        if not render.get("ok") or not preview:
            errors = _unique(render.get("errors") or []) or [_t("Label nicht druckbar")]
            return {"ok": False, "errors": errors, "warnings": warnings}, None
        design = _b64(preview.get("design_png"))
        decision = preview.get("decision") or {}
        if not decision.get("allowed", False):
            errors = _unique(decision.get("reasons") or []) or [_t("Druck abgelehnt")]
            return ({"ok": False, "errors": errors, "warnings": warnings, "limits": self._limits_text()},
                    design)
        digest = _digest(render)
        if digest is None:
            return {"ok": False, "errors": [_t("Vorschau ohne Rasterbild")], "warnings": warnings}, design
        preview_id = self.cache.put(source, options, digest)
        tape_reason = render.get("tape_reason")
        reasons = _unique([*(decision.get("reasons") or []), *([tape_reason] if tape_reason else [])])
        result = {"ok": True, "preview_id": preview_id, "title": render.get("title") or "",
                  "warnings": warnings,
                  "needs_confirmation": bool(decision.get("needs_confirmation")) or bool(tape_reason),
                  "reasons": reasons, "values": render.get("values"), "copies": copies}
        if preview.get("content_mm") is not None:
            result["length_mm"] = preview.get("content_mm")
        if preview.get("tape_mm") is not None:
            result["tape_mm"] = preview.get("tape_mm")
        return result, design

    # ---------- Druck ----------

    def label_print(self, preview_id: str, confirm: bool = False) -> dict:
        if confirm is not True:
            return {"printed": False, "message": _t(MSG_NOT_CONFIRMED)}
        entry = self.cache.get(preview_id)
        if entry is None:
            return {"printed": False, "message": _t(MSG_UNKNOWN)}
        source, options, digest = entry
        render = self.backend.render(source, options)
        if not render.get("ok") or not render.get("preview"):
            self.cache.pop(preview_id)
            return {"printed": False, "message": _t(MSG_STALE_BROKEN)}
        if _digest(render) != digest:
            self.cache.pop(preview_id)
            return {"printed": False, "message": _t(MSG_STALE)}
        if self.cache.pop(preview_id) is None:  # parallel schon verbraucht
            return {"printed": False, "message": _t(MSG_UNKNOWN)}
        outcome = self.backend.print(source, {**options, "confirmed": True})
        return self._outcome(outcome)

    @staticmethod
    def _outcome(outcome: dict) -> dict:
        status = str(outcome.get("status") or "fehler")
        reasons = _unique(outcome.get("reasons") or [])
        title = outcome.get("title") or "Label"
        if status == "ok":
            message = _t("Gedruckt: {title}", title=title)
        elif status == "wartet":
            message = _t("In der Warteschlange (Drucker gerade nicht bereit): {title}", title=title)
        elif status == "abgelehnt":
            message = _t("Abgelehnt: ") + ("; ".join(reasons) or _t("vom Fehldruckschutz"))
        elif status == "bestätigung_nötig":
            message = _t("Nicht gedruckt, Rückfrage offen: ") + ("; ".join(reasons) or _t("bitte in der App drucken"))
        else:
            message = _t("Nicht gedruckt ({status}): ", status=status) + str(outcome.get("error") or "; ".join(reasons) or _t("Fehler"))
        return {"printed": status in ("ok", "wartet"), "status": status, "message": message,
                "queue_id": outcome.get("queue_id"), "warnings": _unique(outcome.get("warnings") or [])}

    # ---------- Zustand ----------

    def printer_status(self) -> dict:
        data = self.backend.status() or {}
        report = data.get("report") or {}
        view = data.get("view") or {}
        state = (report.get("state") or {}).get("state")
        return {"text": view.get("chip") or "", "state": state, "detail": view.get("detail") or ""}

    def print_history(self, limit: int = 10, query: str = "") -> list[dict]:
        if not (isinstance(limit, int) and not isinstance(limit, bool) and 1 <= limit <= MAX_HISTORY):
            raise ValueError(_t("limit muss eine ganze Zahl von 1 bis {max_history} sein", max_history=MAX_HISTORY))
        entries = self.backend.history(limit, str(query or ""))
        keys = ("id", "created", "title", "template", "source", "status", "copies")
        return [{k: e.get(k) for k in keys} for e in entries[:limit]]

    def queue_list(self) -> dict:
        data = self.backend.queue() or {}
        jobs = [{"id": j.get("id"), "state": j.get("state"), "title": j.get("title"), "source": j.get("source"),
                 "created": j.get("created"), "error": j.get("last_error") or None}
                for j in data.get("jobs") or []]
        return {"paused": bool(data.get("paused")), "waiting_reason": data.get("waiting_reason") or "",
                "jobs": jobs}
