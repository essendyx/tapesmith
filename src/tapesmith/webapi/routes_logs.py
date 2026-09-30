"""Routen /api/v1/logs: Protokolldateien auflisten, lesen (Ende, Stufe, Suche), herunterladen.

Nur Rolle `admin`. Erlaubt sind nur Dateien direkt im Ordner `logs` (`tapesmith.logfiles`).
"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from tapesmith import logfiles
from tapesmith.i18n import _t
from tapesmith.webapi.access import require_role
from tapesmith.webapi.errors import NotFound

router = APIRouter(dependencies=[Depends(require_role("admin"))])


def _not_found(name: str) -> NotFound:
    return NotFound(_t("Protokoll '{name}' unbekannt", name=name))


@router.get("/logs", summary="Protokolldateien auflisten")
def get_logs() -> dict:
    return {"files": logfiles.list_logs(), "daemon_log": logfiles.DAEMON_LOG_NAME}


@router.get("/logs/{name}", summary="Protokoll lesen (letzte Zeilen, optional gefiltert)")
def get_log(name: str, lines: int = Query(logfiles.DEFAULT_LINES, ge=1, le=logfiles.MAX_LINES),
            level: str | None = None, search: str | None = Query(None, max_length=200)) -> dict:
    try:
        return logfiles.read_log(name, lines=lines, level=level or None, search=search)
    except logfiles.LogNotFound as exc:
        raise _not_found(name) from exc


@router.get("/logs/{name}/download", summary="Protokoll herunterladen (maskiert)")
def get_log_download(name: str) -> Response:
    try:
        text = logfiles.download_text(name)
    except logfiles.LogNotFound as exc:
        raise _not_found(name) from exc
    return Response(text, media_type="text/plain; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}.txt",
                             "Cache-Control": "no-store"})
