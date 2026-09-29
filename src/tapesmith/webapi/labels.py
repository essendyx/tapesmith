"""Label-Quellen der Web-API: eine Quelle auflösen, als Vorschau rendern, drucken, exportieren.

Vorschau, Druck und Export laufen über denselben Auflösungsweg (`resolve`), damit Vorschau = Druck
gilt. Quellen (`source.kind`): text, template, document, qr, history, calibration, test, image.

`origin` (Quelle des Auftrags, `JobMeta.source`) wird für jede Quellenart nach dem Auflösen
gesetzt; Standard ist `gui`, damit bisherige Aufrufer unverändert bleiben.

Fehlerregeln: kaputte Anfragen (falsche Typen, unbekannte Quelle, kaputte Vorlagen-Definition)
werfen `ValueError`/`TemplateError` (422), unbekannte Vorlagen oder Verlaufseinträge `NotFound` (404).
Alles, was der Nutzer beim Tippen noch korrigieren kann (fehlendes Pflichtfeld, Text passt nicht,
ungültiges Dokument-Objekt), ergibt `ok=False` mit Fehlertext und Status 200.
"""

from __future__ import annotations

import base64
import binascii
import dataclasses
import io
import tempfile
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image

from tapesmith.calibrate import edge_test_head, ruler_content
from tapesmith.document.model import DocumentError, document_from_dict, texts
from tapesmith.document.render import DocumentRender, _describe, render_document, render_spec
from tapesmith.imageinput import ROTATE_MODES, image_to_head
from tapesmith.jobs import SOURCES, JobMeta
from tapesmith.labelmeta import image_meta, qr_meta, text_meta
from tapesmith.pipeline import PrintLabel, PrintOutcome, labels_from_result
from tapesmith.protocol.raster import place_on_head
from tapesmith.render import textsize, zxing
from tapesmith.render.compose import LabelSpec, RenderResult
from tapesmith.render.fixes import diagnose, suggest_fixes
from tapesmith.render.fonts import FONT_FILES, FontMissing
from tapesmith.render.qr import render_qr
from tapesmith.render.qrcontent import (QrCapacity, best_error_level, build_qr_spec, capacity_report,
                                       text_content, url_content, vcard_content, wifi_content)
from tapesmith.render.zxing import NOT_READ_WARNING
from tapesmith.reprint import MissingSecrets, missing_secret_fields, prepare_reprint
from tapesmith.templates.fill import redact, resolve_values
from tapesmith.templates.model import Template, TemplateError, TemplateNotFound, template_from_dict
from tapesmith.templates.render import apply_text_size_spec, render_meta, render_template
from tapesmith.templates.store import find_template
from tapesmith.webapi.errors import NotFound
from tapesmith.webapi.previews import empty_render, png_b64, preview_json
from tapesmith.webapi.printing import PrintOptionsModel, outcome_json, plan_labels, submit_labels
from tapesmith.i18n import N_, _t

if TYPE_CHECKING:  # pragma: no cover
    from tapesmith.webapi.context import ApiContext

NO_TEXT = N_("Kein Text")
MISSING_SECRETS = N_("Sensible Felder neu eingeben: {}")
EDITOR_TITLE = N_("Editor-Label")
RULER_MM = 100
TEST_MAX_MM = 40
IMAGE_TITLE = N_("Bild")
IMAGE_MAX_BYTES = 5 * 1024 * 1024

EXPORT_TYPES = {"png": "image/png", "pdf": "application/pdf", "pbm": "image/x-portable-bitmap"}

FONT_NAMES = {"sans": N_("Sans"), "sans-bold": N_("Sans fett"), "mono": N_("Mono (eindeutige Zeichen)")}

_ALIGNS = ("left", "center", "right")
_QR_LEVELS = ("l", "m", "q", "h")


@dataclass
class Resolved:
    title: str
    labels: tuple[PrintLabel, ...]          # leer, wenn nicht druckbar
    meta: JobMeta | None
    ok: bool
    errors: list[str]
    warnings: list[str]
    issues: list[dict]                      # ObjectIssueJson
    fixes: list[dict]                       # FixJson
    font_size: int | None = None
    qr: dict | None = None                  # QrInfo
    values: dict[str, str] | None = None    # angezeigte Werte (sensible maskiert)
    shortened: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    tape_reason: str | None = None
    confirm_reasons: list[str] = field(default_factory=list)   # zusätzliche Rückfragegründe
    missing_secrets: list[str] = field(default_factory=list)
    editor: dict | None = None              # EditorOverlay
    on_done: Callable[[PrintOutcome], None] | None = None      # z. B. Zähler committen


def _failed(title: str, errors: list[str], **fields) -> Resolved:
    return Resolved(title=title, labels=(), meta=None, ok=False, errors=errors,
                    warnings=fields.pop("warnings", []), issues=fields.pop("issues", []),
                    fixes=fields.pop("fixes", []), **fields)


def _unique(items) -> list[str]:
    return list(dict.fromkeys(items))


# --- Eingaben prüfen ---------------------------------------------------------


class SourceError(ValueError):
    """Ungültige Label-Quelle (Aufbau der Anfrage, nicht der Inhalt): immer ein Fehler (422)."""


def _str(source: dict, key: str, default: str | None = None, *, required: bool = False) -> str | None:
    if key not in source or source[key] is None:
        if required:
            raise SourceError(_t("Label-Quelle: Feld ‚{key}‘ fehlt", key=key))
        return default
    value = source[key]
    if not isinstance(value, str):
        raise SourceError(_t("Label-Quelle: Feld ‚{key}‘ muss ein Text sein", key=key))
    return value


def _bool(source: dict, key: str, default: bool = False) -> bool:
    value = source.get(key, default)
    if not isinstance(value, bool):
        raise SourceError(_t("Label-Quelle: Feld ‚{key}‘ muss true oder false sein", key=key))
    return value


def _number(source: dict, key: str, default: float | None = None) -> float | None:
    value = source.get(key, default)
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise SourceError(_t("Label-Quelle: Feld ‚{key}‘ muss eine Zahl sein", key=key))
    return float(value)


def _lines(source: dict, key: str = "lines", *, required: bool = True) -> list[str]:
    value = source.get(key)
    if value is None and not required:
        return []
    if not isinstance(value, list) or not all(isinstance(line, str) for line in value):
        raise SourceError(_t("Label-Quelle: Feld ‚{key}‘ muss eine Liste von Texten sein", key=key))
    return value


def _values(source: dict) -> dict[str, str]:
    value = source.get("values") or {}
    if not isinstance(value, dict) or not all(isinstance(k, str) and isinstance(v, str)
                                              for k, v in value.items()):
        raise SourceError(_t("Label-Quelle: ‚values‘ muss ein Objekt mit Texten sein"))
    return value


def _trim(lines: list[str]) -> tuple[str, ...]:
    out = list(lines)
    while out and not out[0].strip():
        out.pop(0)
    while out and not out[-1].strip():
        out.pop()
    return tuple(out)


# --- JSON-Bausteine ------------------------------------------------------------

def _issue_json(issue) -> dict:
    return {"object_id": issue.object_id, "level": issue.level, "message": issue.message}


def spec_source(spec: LabelSpec) -> dict:
    """Text-Quelle (`TextSource`) aus einer `LabelSpec` (für Korrekturvorschläge)."""
    return {"kind": "text", "lines": list(spec.lines), "font": spec.font, "align": spec.align,
            "font_size": spec.font_size, "max_length_mm": spec.max_length_mm,
            "fixed_length_mm": spec.fixed_length_mm, "margin_mm": spec.margin_mm, "qr": spec.qr,
            "qr_error": spec.qr_error}


def _fixes_for(spec: LabelSpec, profile) -> list[dict]:
    """Wie `gui.fixbar.problems_for`: Vorschläge nur bei Fehler oder Warnung."""
    diag = diagnose(spec, profile)
    if not (diag.error or diag.warnings):
        return []
    return [{"id": fix.id, "label": fix.title, "source": spec_source(fix.spec)}
            for fix in suggest_fixes(spec, profile)]


def _qr_info(qr) -> dict:
    """QrInfo aus `QrResult` oder `QrCapacity`; `text` wie auf der QR-Seite.
    `checked`: False, wenn der Code mangels Decoder gar nicht erst rückgelesen wurde
    (Warnung `NOT_READ_WARNING`), unabhängig vom `decodes`-Ergebnis."""
    cap = QrCapacity(version=qr.version, error=qr.error, module_dots=qr.module_dots,
                     decodes=qr.decodes, warnings=tuple(qr.warnings))
    return {"version": cap.version, "error": cap.error, "module_dots": cap.module_dots,
            "decodes": cap.decodes, "checked": _t(NOT_READ_WARNING) not in cap.warnings,
            "warnings": list(cap.warnings), "text": cap.text()}


def _editor_json(dr: DocumentRender) -> dict:
    return {
        "png": png_b64(dr.landscape.convert("1")),
        "width": dr.landscape.width,
        "height": dr.landscape.height,
        "boxes": {k: list(v) for k, v in dr.boxes.items()},
        "font_sizes": dict(dr.font_sizes),
        "codes": {k: {"kind": c.kind, "module_dots": c.module_dots, "decodes": c.decodes,
                      "checked": zxing.available(), "inverted": c.inverted, "version": c.version}
                  for k, c in dr.codes.items()},
    }


# --- Quellen -----------------------------------------------------------------

def _render_spec_resolved(ctx: ApiContext, spec: LabelSpec, meta: JobMeta, *,
                          with_fixes: bool = True, extra_warnings=(), qr: dict | None = None) -> Resolved:
    profile = ctx.profile()
    try:
        result = render_spec(spec, profile, ctx.tape())
    except (ValueError, FontMissing) as exc:
        fixes = _fixes_for(spec, profile) if with_fixes and not isinstance(exc, FontMissing) else []
        return _failed(meta.title, [str(exc)], fixes=fixes, qr=qr)
    warnings = _unique([*extra_warnings, *result.warnings])
    fixes = _fixes_for(spec, profile) if with_fixes and warnings else []
    if qr is None and result.qr is not None:
        qr = _qr_info(result.qr)
    elif qr is None and spec.qr:
        # Invertierter Weg über das Dokument liefert kein `RenderResult.qr`: gleiche Größenlogik.
        try:
            qr = _qr_info(render_qr(spec.qr, profile.content_dots, spec.qr_error))
        except ValueError:
            qr = None
    return Resolved(title=meta.title, labels=labels_from_result(result), meta=meta, ok=True, errors=[],
                    warnings=warnings, issues=[], fixes=fixes, font_size=result.font_size, qr=qr)


def _text(ctx: ApiContext, source: dict) -> Resolved:
    lines = _trim(_lines(source))
    if len(lines) > 3:
        raise SourceError(_t("Label-Quelle: höchstens 3 Zeilen"))
    align = _str(source, "align", "left")
    if align not in _ALIGNS:
        raise SourceError(_t("Label-Quelle: Ausrichtung ‚{align}‘ unbekannt", align=align))
    qr_error = _str(source, "qr_error", "m")
    if qr_error not in _QR_LEVELS:
        raise SourceError(_t("Label-Quelle: QR-Fehlerkorrektur ‚{qr_error}‘ unbekannt", qr_error=qr_error))
    font_size = source.get("font_size")
    if font_size is not None and (not isinstance(font_size, int) or isinstance(font_size, bool)
                                  or font_size < 1):
        raise SourceError(_t("Label-Quelle: Schriftgröße muss eine ganze Zahl ab 1 sein"))
    qr = (_str(source, "qr") or "").strip() or None
    if not any(line.strip() for line in lines):
        return _failed("", [_t(NO_TEXT)])
    spec = LabelSpec(lines=lines, font=_str(source, "font", "sans"), align=align, font_size=font_size,
                     max_length_mm=_number(source, "max_length_mm"),
                     fixed_length_mm=_number(source, "fixed_length_mm"),
                     margin_mm=_number(source, "margin_mm", 1.0), qr=qr, qr_error=qr_error)
    size_warnings: tuple[str, ...] = ()
    text_height = _number(source, "text_height_mm")
    if text_height is not None and font_size is None:
        # Feste Texthöhe in mm; passt sie nicht, bleibt die eingepasste Größe (mit Warnung).
        mm = textsize.parse(text_height)
        try:
            auto = render_spec(spec, ctx.profile(), ctx.tape())
        except (ValueError, FontMissing):
            auto = None
        if auto is not None:
            spec, _result, size_warnings = apply_text_size_spec(spec, auto, mm, ctx.profile(), ctx.tape())
    return _render_spec_resolved(ctx, spec, text_meta(spec, source="gui"), extra_warnings=size_warnings)


def _load_template(source: dict) -> Template:
    name = _str(source, "template", required=True)
    definition = source.get("definition")
    if definition is not None:
        if not isinstance(definition, dict):
            raise SourceError(_t("Label-Quelle: ‚definition‘ muss ein Objekt sein"))
        return template_from_dict(definition)
    try:
        return find_template(name)
    except TemplateNotFound as exc:
        raise NotFound(_t("Vorlage '{name}' nicht gefunden", name=name)) from exc


def _template(ctx: ApiContext, source: dict) -> Resolved:
    template = _load_template(source)
    inputs = _values(source)
    counters = ctx.counters()
    try:
        resolved = resolve_values(template, inputs, ctx.now(), counters)
        tr = render_template(template, resolved.values, ctx.profile(), tape=ctx.tape())
        meta = render_meta(tr, source="gui")
    except (TemplateError, ValueError, FontMissing) as exc:
        return _failed(template.name, [str(exc)])

    keys = resolved.counter_keys

    def commit(_outcome: PrintOutcome) -> None:
        for key in keys:
            counters.commit(key)

    reason = tr.tape_reason
    return Resolved(
        title=meta.title, labels=labels_from_result(tr.result), meta=meta, ok=True, errors=[],
        warnings=_unique(tr.warnings), issues=[_issue_json(i) for i in tr.issues], fixes=[],
        font_size=tr.result.font_size,
        qr=_qr_info(tr.result.qr) if tr.result.qr is not None else None,
        values=redact(template, tr.values), shortened=list(tr.shortened), notes=list(tr.notes),
        tape_reason=reason, confirm_reasons=[reason] if reason else [],
        on_done=commit if keys else None)


def _document(ctx: ApiContext, source: dict) -> Resolved:
    raw = source.get("document")
    given_title = _str(source, "title")
    try:
        doc = document_from_dict(raw)
    except DocumentError as exc:
        return _failed(given_title or "", [str(exc)])
    profile = ctx.profile()
    tape = ctx.tape()
    dr = render_document(doc, profile, tape=tape)
    plain = dr
    if doc.mirror or doc.rotate180:
        plain = render_document(dataclasses.replace(doc, mirror=False, rotate180=False), profile, tape=tape)
    title = given_title or " ".join(t for t in texts(doc) if t) or _t(EDITOR_TITLE)
    issues = [_issue_json(i) for i in dr.issues]
    editor = _editor_json(plain)
    warnings = _unique(i.message for i in dr.warnings)
    if dr.errors:
        return _failed(title, [_describe(i) for i in dr.errors], warnings=warnings, issues=issues,
                       editor=editor)
    meta = JobMeta(source="gui", kind="image", title=title)
    font_size = min(dr.font_sizes.values()) if dr.font_sizes else None
    return Resolved(title=title, labels=(PrintLabel(dr.head, dr.landscape),), meta=meta, ok=True,
                    errors=[], warnings=warnings, issues=issues, fixes=[], font_size=font_size,
                    editor=editor)


def _qr_content(content: dict):
    if not isinstance(content, dict):
        raise SourceError(_t("Label-Quelle: ‚content‘ muss ein Objekt sein"))
    kind = content.get("type")
    if kind == "url":
        return url_content(_str(content, "url", ""), uppercase=_bool(content, "uppercase"))
    if kind == "text":
        return text_content(_str(content, "text", ""))
    if kind == "wifi":
        return wifi_content(_str(content, "ssid", ""), _str(content, "password", ""),
                            security=_str(content, "security", "WPA"), hidden=_bool(content, "hidden"))
    if kind == "vcard":
        return vcard_content(_str(content, "name", ""), _str(content, "phone", ""),
                             _str(content, "email", ""), _str(content, "org", ""), _str(content, "url", ""))
    raise SourceError(_t("Unbekannte QR-Art '{kind}'", kind=kind))


def _qr(ctx: ApiContext, source: dict) -> Resolved:
    lines = tuple(line for line in _lines(source, required=False) if line.strip())
    level = _str(source, "error", "auto")
    if level not in ("auto", *_QR_LEVELS):
        raise SourceError(_t("Label-Quelle: QR-Fehlerkorrektur ‚{level}‘ unbekannt", level=level))
    max_mm = _number(source, "max_length_mm")
    content_raw = source.get("content")
    if not isinstance(content_raw, dict):
        raise SourceError(_t("Label-Quelle: ‚content‘ muss ein Objekt sein"))
    try:
        content = _qr_content(content_raw)
    except SourceError:
        raise
    except ValueError as exc:
        return _failed("", [str(exc)])
    profile = ctx.profile()
    try:
        if level == "auto":
            level = best_error_level(content, profile)
        cap = capacity_report(content, profile, level)
    except ValueError as exc:
        return _failed(content.display, [str(exc)])
    spec = build_qr_spec(content, lines, level, max_mm)
    meta = qr_meta(content, lines, source="gui", spec=spec)
    # Korrekturvorschläge sind Text-Quellen mit dem QR-Inhalt: bei sensiblen Inhalten nie anbieten.
    return _render_spec_resolved(ctx, spec, meta, with_fixes=not content.secret,
                                 extra_warnings=cap.warnings, qr=_qr_info(cap))


def _history(ctx: ApiContext, source: dict) -> Resolved:
    entry_id = source.get("id")
    if not isinstance(entry_id, int) or isinstance(entry_id, bool):
        raise SourceError(_t("Label-Quelle: ‚id‘ muss eine ganze Zahl sein"))
    sets = _values(source)
    store = ctx.history()
    try:
        entry = store.get(entry_id)
    except KeyError as exc:
        raise NotFound(_t("Verlaufseintrag {entry_id} gibt es nicht", entry_id=entry_id)) from exc
    title = _t("Nachdruck #{id}: {title}", id=entry.id, title=entry.title)
    missing = [f for f in missing_secret_fields(store, entry) if not sets.get(f)]
    if missing:
        return _failed(title, [_t(MISSING_SECRETS).format(", ".join(missing))], missing_secrets=missing)
    try:
        job = prepare_reprint(store, entry, ctx.profile(), sets=sets, source="gui", now=ctx.now,
                              counters=ctx.counters(), tape=ctx.tape())
    except MissingSecrets as exc:
        return _failed(title, [_t(MISSING_SECRETS).format(", ".join(exc.fields))],
                       missing_secrets=list(exc.fields))
    except (TemplateError, ValueError, FontMissing) as exc:
        return _failed(title, [str(exc)])
    result: RenderResult | None = job.result
    warnings = list(result.warnings) if result is not None else []

    def commit(_outcome: PrintOutcome) -> None:
        job.commit_counters()

    return Resolved(title=job.meta.title, labels=job.labels, meta=job.meta, ok=True, errors=[],
                    warnings=_unique(warnings), issues=[], fixes=[],
                    font_size=result.font_size if result is not None else None,
                    qr=_qr_info(result.qr) if result is not None and result.qr is not None else None,
                    values=dict(entry.values) if entry.values else None,
                    on_done=commit if job.counter_keys else None)


def _calibration(ctx: ApiContext, source: dict) -> Resolved:
    which = source.get("which")
    profile = ctx.profile()
    if which == "ruler":
        head = place_on_head(ruler_content(profile, RULER_MM), profile)
        title = _t("Kalibrierung Lineal")
    elif which == "edge":
        head = edge_test_head(profile)
        title = _t("Kalibrierung Kantentest")
    else:
        raise ValueError(_t("Unbekannte Kalibrierung '{which}' (möglich: ruler, edge)", which=which))
    meta = JobMeta(source="gui", kind="calibrate", title=title)
    return Resolved(title=title, labels=(PrintLabel(head),), meta=meta, ok=True, errors=[], warnings=[],
                    issues=[], fixes=[])


def _test(ctx: ApiContext, _source: dict) -> Resolved:
    spec = LabelSpec(lines=("Tapesmith", "Test " + ctx.now().strftime("%d.%m.%Y %H:%M")),
                     max_length_mm=TEST_MAX_MM)
    title = _t("Testlabel")
    resolved = _render_spec_resolved(ctx, spec, JobMeta(source="gui", kind="test", title=title),
                                     with_fixes=False)
    resolved.title = title
    return resolved


def _decode_png(source: dict) -> bytes:
    data = _str(source, "png", required=True)
    # Obergrenze schon vor dem Dekodieren prüfen (Base64 ist etwa 4/3 so lang wie die Daten).
    if len(data) > (IMAGE_MAX_BYTES // 3 + 1) * 4 + 16:
        raise SourceError(_t("Label-Quelle: Bild größer als {value} MB", value=IMAGE_MAX_BYTES // (1024 * 1024)))
    try:
        raw = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SourceError(_t("Label-Quelle: ‚png‘ ist kein gültiges Base64")) from exc
    if len(raw) > IMAGE_MAX_BYTES:
        raise SourceError(_t("Label-Quelle: Bild größer als {value} MB", value=IMAGE_MAX_BYTES // (1024 * 1024)))
    return raw


def _image(ctx: ApiContext, source: dict) -> Resolved:
    raw = _decode_png(source)
    title = _str(source, "name") or _t(IMAGE_TITLE)
    threshold = source.get("threshold", 128)
    if not isinstance(threshold, int) or isinstance(threshold, bool) or not 0 <= threshold <= 255:
        raise SourceError(_t("Label-Quelle: ‚threshold‘ muss eine ganze Zahl von 0 bis 255 sein"))
    rotate = _str(source, "rotate", "auto")
    if rotate not in ROTATE_MODES:
        raise SourceError(_t("Label-Quelle: ‚rotate‘ muss {items} sein", items=', '.join(ROTATE_MODES)))
    fit = _bool(source, "fit")
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except Exception as exc:  # noqa: BLE001 (Pillow wirft viele Arten bei kaputten Bildern)
        return _failed(title, [_t("Bild nicht lesbar: {exc}", exc=exc)])
    try:
        # Kein `with`: ein Bild im Modus "1" mit Kopfbreite wird unverändert übernommen.
        head = image_to_head(img, ctx.profile(), threshold=threshold, rotate=rotate, fit=fit)
    except ValueError as exc:
        # Zu große Bilder usw.: der Nutzer kann das Bild anpassen (ok=False statt 422).
        return _failed(title, [str(exc)])
    meta = image_meta(title, source="gui")
    return Resolved(title=title, labels=(PrintLabel(head=head),), meta=meta, ok=True, errors=[],
                    warnings=[], issues=[], fixes=[])


_KINDS: dict[str, Callable[[ApiContext, dict], Resolved]] = {
    "text": _text, "template": _template, "document": _document, "qr": _qr, "history": _history,
    "calibration": _calibration, "test": _test, "image": _image,
}


# --- Öffentliche Schnittstelle ------------------------------------------------

def resolve(ctx: ApiContext, source: dict, *, origin: str = "gui") -> Resolved:
    """Löst eine Label-Quelle zu druckfertigen Labels auf (dieselben für Vorschau, Druck, Export).

    `origin` ist die Quelle des Auftrags (`JobMeta.source`, steuert Kontingente und Verlauf)."""
    if origin not in SOURCES:
        raise ValueError(_t("Unbekannte Quelle '{origin}' (erlaubt: {items})", origin=origin, items=', '.join(SOURCES)))
    if not isinstance(source, dict):
        raise SourceError(_t("Label-Quelle muss ein Objekt sein"))
    kind = source.get("kind")
    handler = _KINDS.get(kind) if isinstance(kind, str) else None
    if handler is None:
        raise ValueError(_t("Unbekannte Label-Quelle '{kind}'", kind=kind))
    resolved = handler(ctx, source)
    if resolved.meta is not None and resolved.meta.source != origin:
        resolved.meta = dataclasses.replace(resolved.meta, source=origin)
    return resolved


def render_json(ctx: ApiContext, resolved: Resolved, opts: PrintOptionsModel) -> dict:
    """`RenderJson`: Vorschau nur bei druckbaren Labels."""
    preview = None
    if resolved.ok and resolved.labels and resolved.meta is not None:
        preview = preview_json(ctx, resolved.labels, resolved.meta, opts, extra_warnings=resolved.warnings)
    return empty_render(
        resolved.title, ok=resolved.ok, preview=preview, errors=list(resolved.errors),
        warnings=list(resolved.warnings), issues=list(resolved.issues), fixes=list(resolved.fixes),
        font_size=resolved.font_size, qr=resolved.qr, values=resolved.values,
        shortened=list(resolved.shortened), notes=list(resolved.notes), tape_reason=resolved.tape_reason,
        missing_secrets=list(resolved.missing_secrets), editor=resolved.editor)


class LabelNotPrintable(ValueError):
    """Quelle ist nicht druckbar: 422 mit `kind: "Label"` (Routen bauen die Antwort)."""

    def __init__(self, resolved: Resolved):
        super().__init__("; ".join(resolved.errors) or _t("Label nicht druckbar"))
        self.resolved = resolved

    def details(self) -> dict:
        return {"errors": list(self.resolved.errors), "missing_secrets": list(self.resolved.missing_secrets)}


def _printable(ctx: ApiContext, source: dict, origin: str = "gui") -> Resolved:
    resolved = resolve(ctx, source, origin=origin)
    if not resolved.ok or not resolved.labels or resolved.meta is None:
        raise LabelNotPrintable(resolved)
    return resolved


def print_source(ctx: ApiContext, source: dict, opts: PrintOptionsModel, *, origin: str = "gui") -> dict:
    """`OutcomeJson`; bei offenen Rückfragegründen ohne `confirmed` wird nicht gedruckt."""
    resolved = _printable(ctx, source, origin)
    if resolved.confirm_reasons and not opts.confirmed:
        job_key = opts.job_key or uuid.uuid4().hex
        plan = plan_labels(ctx, resolved.labels, resolved.meta, opts)
        reasons = list(resolved.confirm_reasons)
        if plan.decision.needs_confirmation:
            reasons += list(plan.decision.reasons)
        outcome = PrintOutcome("bestätigung_nötig", plan, reasons=tuple(_unique(reasons)))
        return outcome_json(outcome, job_key=job_key)
    return submit_labels(ctx, resolved.labels, resolved.meta, opts, on_done=resolved.on_done)


def export_source(ctx: ApiContext, source: dict, opts: PrintOptionsModel, fmt: str, *,
                  origin: str = "gui") -> tuple[bytes, str, str]:
    """(Daten, Medientyp, Dateiname) des Exports als PNG, PDF oder PBM."""
    if fmt not in EXPORT_TYPES:
        raise ValueError(_t("Unbekanntes Exportformat '{fmt}' (erlaubt: png, pdf, pbm)", fmt=fmt))
    resolved = _printable(ctx, source, origin)
    plan = plan_labels(ctx, resolved.labels, resolved.meta, opts)
    with tempfile.TemporaryDirectory(prefix="p12-export-") as tmp:
        written = ctx.service.pipeline.export(plan, Path(tmp) / f"label.{fmt}", fmt)
        data = Path(written).read_bytes()
    name = f"label-{ctx.now().strftime('%Y%m%d-%H%M%S')}.{fmt}"
    return data, EXPORT_TYPES[fmt], name


def font_list() -> list[dict]:
    return [{"id": font_id, "name": _t(FONT_NAMES.get(font_id, font_id))} for font_id in FONT_FILES]
