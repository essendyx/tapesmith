"""Routen /api/v1 (Bereich family): handyoptimierte Familien-Druckseite.

Nur freigegebene Vorlagen (`family.templates`), Vorschau, Druck mit Kopiengrenze
(`sourcelimits.family_max_copies`), einfacher Druckerstatus. Keine Einstellungen, kein Verlauf,
keine Rohbefehle, keine freien Quellen. Rollen `admin`, `drucken`, `familie`; Quelle der Aufträge
immer `api` (`confirmed` wirkt nur für die Band-Rückfrage).

Zusätzlich die eingebaute Sondervorlage `freitext` (`family.freetext_enabled`, Standard an):
ein einzelnes mehrzeiliges Textfeld ohne Vorlage aus dem Speicher, mit eigener Längengrenze
(`FREETEXT_MAX_LEN`). Dieselbe Kopiengrenze und dieselbe Quelle `api` wie jede andere
Familienvorlage.
"""

from __future__ import annotations

import unicodedata

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from tapesmith import config as config_mod
from tapesmith import pipeline, sourcelimits
from tapesmith.templates import gallery as gallery_mod
from tapesmith.templates import store
from tapesmith.templates.fill import input_fields
from tapesmith.templates.model import Field, Template, TemplateError
from tapesmith.webapi.access import ROLE_ADMIN, ROLE_FAMILY, ROLE_PRINT, require_role
from tapesmith.webapi.context import ApiContext, get_ctx
from tapesmith.webapi.errors import NotFound, error_json
from tapesmith.webapi.labels import LabelNotPrintable, print_source, render_json, resolve
from tapesmith.webapi.printing import options_from_json
from tapesmith.i18n import N_, _t

router = APIRouter(dependencies=[Depends(require_role(ROLE_ADMIN, ROLE_PRINT, ROLE_FAMILY))])

ORIGIN = "api"
MAX_VALUE_LEN = 200
NOT_ALLOWED = N_("Vorlage nicht freigegeben")

# Eingebaute Sondervorlage fuer eigenen Text (kein Template aus dem Speicher), nur mit
# family.freetext_enabled (Standard an). Eigene Laengengrenze statt MAX_VALUE_LEN, damit sie sich
# unabhaengig von echten Vorlagenfeldern aendern laesst.
FREETEXT_NAME = "freitext"
FREETEXT_MAX_LEN = 200

TAPE_CONFIRM_MESSAGE = N_("Das eingelegte Band passt nicht zu dieser Vorlage. Trotzdem drucken?")
WAITING_MESSAGE = N_("Drucker ist aus: der Auftrag wartet und wird automatisch gedruckt.")
LABEL_TOO_LONG_MESSAGE = N_("Das Etikett ist zu lang für den Druck vom Handy.")
DOUBLE_PRESS_MESSAGE = N_("Gerade eben schon gedruckt. Bitte kurz warten.")
QUOTA_MESSAGE = N_("Für heute bzw. diese Stunde sind genug Etiketten gedruckt.")
PRINTED_MESSAGE = N_("Gedruckt.")
PRINTING_CONNECTING = N_("Drucker verbindet…")
PRINTER_READY = N_("Drucker bereit")
PRINTER_OFFLINE = N_("Drucker aus, Aufträge werden gesammelt")
STATUS_FRESH_S = 300.0


# ================================================================ Anfragekörper


class FamilyPreviewBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    template: str
    values: dict[str, str] = {}


class FamilyPrintBody(FamilyPreviewBody):
    copies: int = 1
    confirmed: bool = False


# ================================================================ Hilfsfunktionen


def _visible_fields(t: Template) -> list[Field] | None:
    """Eingabefelder ohne `secret`; None, wenn ein sensibles Feld Pflicht ist (Vorlage nie anbieten)."""
    fields = input_fields(t)
    if any(f.secret and f.required for f in fields):
        return None
    return [f for f in fields if not f.secret]


def _title(t: Template) -> str:
    if t.description:
        return t.description
    name = t.display_title
    return name[:1].upper() + name[1:]


def _family_field_json(f: Field) -> dict:
    return {"id": f.id, "label": f.label, "type": f.type, "default": f.default,
            "required": f.required, "choices": list(f.choices), "choice_labels": dict(f.choice_labels),
            "max_len": f.max_len, "multiline": f.multiline}


def _family_template_json(t: Template, fields: list[Field]) -> dict:
    ids = {f.id for f in fields}
    sample = {k: v for k, v in gallery_mod.sample_values(t).items() if k in ids}
    return {"name": t.name, "title": _title(t), "description": t.description,
            "category": t.category or _t("Allgemein"), "fields": [_family_field_json(f) for f in fields],
            "sample": sample}


def _allowed_names(cfg: dict) -> list[str]:
    return list(config_mod.setting(cfg, "family.templates") or ())


def _freetext_enabled(cfg: dict) -> bool:
    return bool(config_mod.setting(cfg, "family.freetext_enabled"))


def _freetext_field() -> Field:
    return Field(id="text", label=_t("Freitext"), type="input", default="", required=True,
                 max_len=FREETEXT_MAX_LEN, multiline=True)


def _freetext_template_json() -> dict:
    return {"name": FREETEXT_NAME, "title": _t("Freitext"), "description": _t("Eigener Text"),
            "category": _t("Allgemein"), "fields": [_family_field_json(_freetext_field())], "sample": {}}


def _source_for(name: str, values: dict[str, str]) -> dict:
    if name == FREETEXT_NAME:
        return {"kind": "text", "lines": values.get("text", "").split("\n")}
    return {"kind": "template", "template": name, "values": values}


def _find_allowed(cfg: dict, name: str) -> tuple[Template | None, list[Field]]:
    """Vorlage nur, wenn ihr Name in `family.templates` steht, sie existiert und nach dem
    Filtern sensibler Felder alle Pflichtfelder übrig sind; sonst 404. `freitext`
    ist die eingebaute Sondervorlage (kein Template aus dem Speicher, keine echte
    `Template`), nur mit `family.freetext_enabled`."""
    if name == FREETEXT_NAME:
        if not _freetext_enabled(cfg):
            raise NotFound(_t(NOT_ALLOWED))
        return None, [_freetext_field()]
    if name not in _allowed_names(cfg):
        raise NotFound(_t(NOT_ALLOWED))
    try:
        t = store.find_template(name)
    except TemplateError as exc:
        raise NotFound(_t(NOT_ALLOWED)) from exc
    fields = _visible_fields(t)
    if fields is None:
        raise NotFound(_t(NOT_ALLOWED))
    return t, fields


def _validate_values(fields: list[Field], values: dict[str, str]) -> None:
    """`values` gegen die Eingabefelder prüfen: bekannte Feld-ids, Länge, Steuerzeichen, Auswahl."""
    known = {f.id: f for f in fields}
    unknown = sorted(set(values) - set(known))
    if unknown:
        raise ValueError(_t("Unbekannte Feld(er): {items}", items=', '.join(unknown)))
    for field_id, value in values.items():
        field = known[field_id]
        limit = field.max_len if field.max_len is not None else MAX_VALUE_LEN
        if len(value) > limit:
            raise ValueError(_t("Feld '{label}': höchstens {limit} Zeichen", label=field.label, limit=limit))
        for ch in value:
            if unicodedata.category(ch) == "Cc" and not (ch == "\n" and field.multiline):
                raise ValueError(_t("Feld '{label}': Steuerzeichen nicht erlaubt", label=field.label))
        if field.choices and value and value not in field.choices:
            raise ValueError(_t("Feld '{label}': Wert muss einer der vorgegebenen Werte sein", label=field.label))


def _reject_message(reasons: list[str]) -> str:
    if any("kann nicht bestätigen" in r for r in reasons):
        return _t(LABEL_TOO_LONG_MESSAGE)
    if reasons == [pipeline.DOUBLE_PRESS_REASON]:
        return _t(DOUBLE_PRESS_MESSAGE)
    if not reasons:
        return _t("Druck abgelehnt.")
    parts = [f"{_t(QUOTA_MESSAGE)} ({r})" if "Kontingent" in r else r for r in reasons]
    return " ".join(parts)


def _family_result(outcome: dict) -> dict:
    status = outcome["status"]
    reasons = list(outcome.get("reasons") or [])
    if status == "ok":
        message = _t(PRINTED_MESSAGE)
    elif status == "wartet":
        message = _t(WAITING_MESSAGE)
    elif status == "bestätigung_nötig":
        message = _t(TAPE_CONFIRM_MESSAGE)
    elif status == "abgelehnt":
        message = _reject_message(reasons)
    else:
        error = outcome.get("error") or {}
        message = _t("Druck fehlgeschlagen: {get}", get=error.get('message', ''))
    return {"status": status, "message": message, "reasons": reasons, "queue_id": outcome.get("queue_id")}


def _not_printable(exc: LabelNotPrintable) -> JSONResponse:
    return JSONResponse(error_json("Label", str(exc), details=exc.details()), status_code=422)


# ================================================================ Routen


@router.get("/familie/vorlagen")
def family_templates(ctx: ApiContext = Depends(get_ctx)) -> dict:
    cfg = ctx.config()
    templates = []
    for name in _allowed_names(cfg):
        try:
            t = store.find_template(name)
        except TemplateError:
            continue
        fields = _visible_fields(t)
        if fields is None:
            continue
        templates.append(_family_template_json(t, fields))
    if _freetext_enabled(cfg):
        templates.append(_freetext_template_json())
    return {"templates": templates, "max_copies": sourcelimits.family_max_copies(cfg)}


@router.post("/familie/vorschau")
def family_preview(body: FamilyPreviewBody, ctx: ApiContext = Depends(get_ctx)) -> dict:
    cfg = ctx.config()
    _tpl, fields = _find_allowed(cfg, body.template)
    _validate_values(fields, body.values)
    source = _source_for(body.template, body.values)
    rendered = render_json(ctx, resolve(ctx, source, origin=ORIGIN), options_from_json(None))
    preview = rendered.get("preview")
    return {
        "ok": rendered["ok"], "errors": rendered["errors"], "warnings": rendered["warnings"],
        "design_png": preview["design_png"] if preview else None,
        "width": preview["width"] if preview else None,
        "height": preview["height"] if preview else None,
        "length_mm": preview["content_mm"] if preview else None,
    }


@router.post("/familie/drucken")
def family_print(body: FamilyPrintBody, ctx: ApiContext = Depends(get_ctx)):
    cfg = ctx.config()
    _tpl, fields = _find_allowed(cfg, body.template)
    _validate_values(fields, body.values)
    limit = sourcelimits.family_max_copies(cfg)
    copies = body.copies
    if not (isinstance(copies, int) and not isinstance(copies, bool) and 1 <= copies <= limit):
        raise ValueError(_t("Höchstens {limit} Kopien", limit=limit))
    source = _source_for(body.template, body.values)
    opts = options_from_json({"copies": copies, "confirmed": body.confirmed})
    try:
        outcome = print_source(ctx, source, opts, origin=ORIGIN)
    except LabelNotPrintable as exc:
        return _not_printable(exc)
    return _family_result(outcome)


@router.get("/familie/status")
def family_status(ctx: ApiContext = Depends(get_ctx)) -> dict:
    report = ctx.service.status(fresh=False)
    state = report.state.state
    online = state == "verbunden"
    if not online and report.checked_at is not None:
        online = (ctx.now() - report.checked_at).total_seconds() < STATUS_FRESH_S
    if online:
        text = _t(PRINTER_READY)
    elif state == "verbindet":
        text = _t(PRINTING_CONNECTING)
    else:
        text = _t(PRINTER_OFFLINE)
    waiting = len(ctx.service.queue_snapshot()["jobs"])
    return {"online": online, "text": text, "waiting": waiting}
