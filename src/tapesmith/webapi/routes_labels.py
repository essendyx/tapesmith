"""Routen /api/v1 (Bereich labels).

Rendern, Drucken und Exportieren jeder Label-Quelle über `webapi.labels` (Vorschau = Druck),
dazu die letzten Schnelldruck-Texte und die verfügbaren Schriften.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict

from tapesmith.gui.recent import recent_texts
from tapesmith.webapi import access
from tapesmith.webapi.context import ApiContext, get_ctx
from tapesmith.webapi.errors import error_json
from tapesmith.webapi.labels import (LabelNotPrintable, export_source, font_list, print_source, render_json,
                                    resolve)
from tapesmith.webapi.printing import options_from_json

router = APIRouter()


class LabelBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    source: dict[str, Any]
    options: dict[str, Any] | None = None


class ExportBody(LabelBody):
    format: str


def _not_printable(exc: LabelNotPrintable) -> JSONResponse:
    return JSONResponse(error_json("Label", str(exc), details=exc.details()), status_code=422)


@router.post("/labels/render")
def render_label(body: LabelBody, request: Request, ctx: ApiContext = Depends(get_ctx)) -> dict:
    opts = options_from_json(body.options)
    return render_json(ctx, resolve(ctx, body.source, origin=access.job_origin(request)), opts)


@router.post("/labels/print")
def print_label(body: LabelBody, request: Request, ctx: ApiContext = Depends(get_ctx)):
    opts = options_from_json(body.options)
    try:
        return print_source(ctx, body.source, opts, origin=access.job_origin(request))
    except LabelNotPrintable as exc:
        return _not_printable(exc)


@router.post("/labels/export")
def export_label(body: ExportBody, request: Request, ctx: ApiContext = Depends(get_ctx)):
    opts = options_from_json(body.options)
    try:
        data, media_type, name = export_source(ctx, body.source, opts, body.format,
                                               origin=access.job_origin(request))
    except LabelNotPrintable as exc:
        return _not_printable(exc)
    return Response(data, media_type=media_type,
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/labels/recent-texts")
def recent(n: int = Query(5, ge=1, le=50), ctx: ApiContext = Depends(get_ctx)) -> dict:
    return {"items": [list(lines) for lines in recent_texts(ctx.history(), n, source="gui")]}


@router.get("/labels/fonts")
def fonts() -> dict:
    return {"fonts": font_list()}
