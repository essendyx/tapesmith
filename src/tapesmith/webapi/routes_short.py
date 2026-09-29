"""Routen /api/v1: stabile externe Kurzschnittstelle für Rollen `admin`, `drucken`.

`POST /print`, `POST /print/text`, `GET /preview.png`, `GET /jobs`, `DELETE /jobs/{id}`,
`GET /docs`. Die Rollen-Tabelle (`webapi.access.allowed`) erlaubt diese Pfade schon für
`drucken`; hier kommt keine eigene Rollenprüfung dazu, `familie` bleibt über die Tabelle gesperrt.
"""

from __future__ import annotations

import base64
import html
import json
import re
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from tapesmith.webapi import access
from tapesmith.webapi.context import ApiContext, get_ctx
from tapesmith.webapi.labels import LabelNotPrintable, print_source, resolve
from tapesmith.webapi.previews import preview_json
from tapesmith.webapi.printing import PrintOptionsModel, options_from_json
from tapesmith.i18n import _t

router = APIRouter()

CSP_HEADER = "default-src 'none'; style-src 'unsafe-inline'"


def _not_printable(exc: LabelNotPrintable) -> JSONResponse:
    from tapesmith.webapi.errors import error_json

    return JSONResponse(error_json("Label", str(exc), details=exc.details()), status_code=422)


class _RawBody(dict):
    """Kleines Hilfsmittel, damit FastAPI beliebiges JSON als dict entgegennimmt."""


def _print_options(copies: int | None, confirmed: bool | None) -> dict[str, Any]:
    data: dict[str, Any] = {}
    if copies is not None:
        data["copies"] = copies
    if confirmed is not None:
        data["confirmed"] = confirmed
    return data


# ---------- POST /print ----------

async def _read_json_body(request: Request) -> dict:
    try:
        data = await request.json()
    except Exception as exc:  # noqa: BLE001
        raise ValueError(_t("Ungültige Anfrage: kein gültiges JSON")) from exc
    if not isinstance(data, dict):
        raise ValueError(_t("Ungültige Anfrage: Körper muss ein Objekt sein"))
    return data


@router.post("/print", summary="Etikett drucken (Vorlage oder Quelle)")
async def post_print(request: Request, ctx: ApiContext = Depends(get_ctx)):
    body = await _read_json_body(request)
    has_template = "template" in body and body["template"] is not None
    has_source = "source" in body and body["source"] is not None
    if has_template == has_source:
        raise ValueError(_t("Ungültige Anfrage: genau eins von 'template' oder 'source' angeben"))
    if has_template:
        if not isinstance(body["template"], str):
            raise ValueError(_t("Ungültige Anfrage: Feld 'template' muss ein Text sein"))
        source = {"kind": "template", "template": body["template"], "values": body.get("values") or {}}
        opts_data = _print_options(body.get("copies"), body.get("confirmed"))
    else:
        source = body["source"]
        opts_data = body.get("options")
    opts = options_from_json(opts_data)
    try:
        return print_source(ctx, source, opts, origin=access.job_origin(request))
    except LabelNotPrintable as exc:
        return _not_printable(exc)


# ---------- POST /print/text ----------

@router.post("/print/text", summary="Textetikett drucken (höchstens 3 Zeilen)")
async def post_print_text(request: Request, ctx: ApiContext = Depends(get_ctx)):
    body = await _read_json_body(request)
    has_lines = "lines" in body and body["lines"] is not None
    has_text = "text" in body and body["text"] is not None
    if has_lines == has_text:
        raise ValueError(_t("Ungültige Anfrage: genau eins von 'lines' oder 'text' angeben"))
    if has_lines:
        lines = body["lines"]
        if not isinstance(lines, list) or not all(isinstance(line, str) for line in lines):
            raise ValueError(_t("Ungültige Anfrage: Feld 'lines' muss eine Liste von Texten sein"))
    else:
        text = body["text"]
        if not isinstance(text, str):
            raise ValueError(_t("Ungültige Anfrage: Feld 'text' muss ein Text sein"))
        lines = text.split("\n")
    source: dict[str, Any] = {"kind": "text", "lines": lines}
    for key in ("font", "align", "qr"):
        if body.get(key) is not None:
            source[key] = body[key]
    opts_data = _print_options(body.get("copies"), body.get("confirmed"))
    opts = options_from_json(opts_data)
    try:
        return print_source(ctx, source, opts, origin=access.job_origin(request))
    except LabelNotPrintable as exc:
        return _not_printable(exc)


# ---------- GET /preview.png ----------

def _parse_values(raw: str | None) -> dict[str, str]:
    if raw is None:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(_t("Ungültige Anfrage: 'values' enthält kein gültiges JSON")) from exc
    if not isinstance(parsed, dict) or not all(isinstance(k, str) and isinstance(v, str)
                                               for k, v in parsed.items()):
        raise ValueError(_t("Ungültige Anfrage: 'values' muss ein Objekt mit Texten sein"))
    return parsed


@router.get("/preview.png", summary="Vorschau- oder Druckbild eines Etiketts")
def get_preview_png(request: Request, template: str | None = None, text: str | None = None,
                    values: str | None = None, raster: int = 0,
                    ctx: ApiContext = Depends(get_ctx)):
    if bool(template) == bool(text):
        raise ValueError(_t("Ungültige Anfrage: genau eins von 'template' oder 'text' angeben"))
    if template:
        source = {"kind": "template", "template": template, "values": _parse_values(values)}
    else:
        source = {"kind": "text", "lines": text.split("\n")}
    origin = access.job_origin(request)
    resolved = resolve(ctx, source, origin=origin)
    if not resolved.ok or not resolved.labels or resolved.meta is None:
        return _not_printable(LabelNotPrintable(resolved))
    preview = preview_json(ctx, resolved.labels, resolved.meta, PrintOptionsModel())
    data = base64.b64decode(preview["raster_png" if raster else "design_png"])
    return Response(data, media_type="image/png")


# ---------- GET /jobs, DELETE /jobs/{id} ----------

@router.get("/jobs", summary="Warteschlange abrufen (wie GET /queue)")
def get_jobs(include_done: bool = False, ctx: ApiContext = Depends(get_ctx)) -> dict:
    return ctx.service.queue_snapshot(include_done)


@router.delete("/jobs/{job_id}", summary="Wartenden Auftrag abbrechen")
def delete_job(job_id: int, ctx: ApiContext = Depends(get_ctx)) -> dict:
    return {"ok": bool(ctx.service.queue_cancel(job_id))}


# ---------- GET /docs ----------

_PARAM_RE = re.compile(r"\{([^{}]+)\}")
_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")


def _example_path(path: str) -> str:
    def repl(match: re.Match) -> str:
        name = match.group(1)
        return "1" if name == "id" or name.endswith("_id") else "x"

    return _PARAM_RE.sub(repl, path)


def _roles_for(method: str, path: str) -> str:
    example = _example_path(path)
    roles = ["admin"]
    for role in (access.ROLE_PRINT, access.ROLE_FAMILY):
        if access.allowed(role, method, example):
            roles.append(role)
    return ", ".join(roles)


@router.get("/docs", summary="Übersicht aller API-Routen (diese Seite)")
def get_docs(request: Request) -> HTMLResponse:
    spec = request.app.openapi()
    rows: list[tuple[str, str, str, str]] = []
    for path, methods in spec.get("paths", {}).items():
        for method, op in methods.items():
            method_upper = method.upper()
            if method_upper not in _METHODS or not isinstance(op, dict):
                continue
            summary = op.get("summary") or op.get("operationId") or ""
            rows.append((method_upper, path, summary, _roles_for(method_upper, path)))
    rows.sort(key=lambda r: (r[1], r[0]))
    body_rows = "".join(
        "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
            html.escape(m), html.escape(p), html.escape(s), html.escape(r))
        for m, p, s, r in rows
    )
    page = (
        _t("<!doctype html>\n<html lang=\"de\"><head><meta charset=\"utf-8\"><title>Tapesmith API</title></head>\n<body>\n<h1>Tapesmith API</h1>\n<p>Authentisierung per <code>Authorization: Bearer &lt;token&gt;</code>. Schema unter <code>/api/v1/openapi.json</code>.</p>\n<table border=\"1\">\n<thead><tr><th>Methode</th><th>Pfad</th><th>Zusammenfassung</th><th>Rollen</th></tr></thead>\n<tbody>{body_rows}</tbody>\n</table>\n</body></html>\n", body_rows=body_rows)
    )
    return HTMLResponse(page, headers={"Content-Security-Policy": CSP_HEADER})
