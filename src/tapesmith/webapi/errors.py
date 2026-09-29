"""Einheitliche Fehlerantworten der API (mit stabilem Fehlercode aus `errors.ERROR_CODES`).

Körper immer `{"error": {"kind", "code", "message", "hint", "exit_code", "details"}}`; `code` ist
stabil (`tapesmith.errors.ERROR_CODES`), `hint` und `exit_code` kommen aus `tapesmith.errors.explain`.
Nie ein Traceback in der Antwort; unerwartete Ausnahmen werden mit `log.exception` protokolliert.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from tapesmith.document.model import DocumentError
from tapesmith.errors import CODE_STATUS, EXIT_ERROR, error_code, explain, http_status_code
from tapesmith.fileutil import FileLockTimeout
from tapesmith.ipc.protocol import IpcError, ProtocolError
from tapesmith.lock import PrinterBusy
from tapesmith.templates.model import TemplateError
from tapesmith.transport.base import ConnectTimeout, TransportError
from tapesmith.i18n import N_, _t

log = logging.getLogger(__name__)

_HTTP_KINDS = {400: "BadRequest", 401: "Unauthorized", 403: "Forbidden", 404: "NotFound",
               405: "MethodNotAllowed", 409: "Conflict", 413: "TooLarge", 422: "Validierung"}


class NotFound(LookupError):
    """Angefragtes Objekt (Vorlage, Dokument, Verlaufseintrag …) gibt es nicht: 404."""

    def __str__(self) -> str:
        # LookupError/KeyError-Darstellung ohne Anführungszeichen
        return str(self.args[0]) if self.args else ""


# Code für Aufrufe von `error_json` ohne ausdrücklichen Code, abgeleitet aus `kind`. So liefern auch
# Routen, die den Körper selbst bauen (z. B. `kind="Label"` oder `kind="SSH"`), einen passenden Code.
_KIND_CODES = {
    "Label": "label.not_printable", "SSH": "integration.upstream", "Validierung": "value.invalid",
    "Conflict": "conflict", "Dienst läuft": "conflict", "TemplateError": "template.invalid",
    "DocumentError": "document.invalid", "Unauthorized": "auth.required", "Forbidden": "auth.forbidden",
    "NotFound": "not_found", "MethodNotAllowed": "method.not_allowed", "TooLarge": "too_large",
    "PrinterBusy": "printer.busy",
}


def error_json(kind: str, message: str, *, code: str | None = None, hint: str = "",
               exit_code: int = EXIT_ERROR, details: dict | None = None) -> dict:
    """Fehlerkörper in fester Schlüsselreihenfolge. Ohne `code` gilt der Code zu `kind` aus
    `_KIND_CODES`, sonst `internal`."""
    if code is None:
        code = _KIND_CODES.get(kind, "internal")
    return {"error": {"kind": kind, "code": code, "message": message, "hint": hint, "exit_code": exit_code,
                      "details": details}}


def _status_for(exc: BaseException) -> int:
    status = getattr(exc, "http_status", None)
    if isinstance(status, int) and not isinstance(status, bool) and 400 <= status <= 599:
        return status
    own = getattr(exc, "code", None)
    if isinstance(own, str) and own in CODE_STATUS:
        return CODE_STATUS[own]
    if isinstance(exc, NotFound):
        return 404
    if isinstance(exc, (TemplateError, DocumentError, ValueError, KeyError, ProtocolError)):
        return 422
    if isinstance(exc, (PrinterBusy, FileLockTimeout)):
        return 409
    if isinstance(exc, (ConnectTimeout, TransportError, IpcError)):
        return 503
    return 500


def _message(exc: BaseException) -> str:
    if isinstance(exc, KeyError) and not isinstance(exc, NotFound) and exc.args:
        return str(exc.args[0])
    return str(exc)


def error_body(exc: BaseException) -> tuple[int, dict]:
    """(HTTP-Status, Fehlerkörper) für eine Ausnahme aus Dienst, Kern oder Validierung."""
    status = _status_for(exc)
    code = error_code(exc)
    if status == 404:
        return status, error_json(type(exc).__name__, _message(exc), code=code)
    advice = explain(exc)
    hint = advice.hint
    own_hint = getattr(exc, "hint", None)
    if not hint and isinstance(own_hint, str):
        hint = own_hint
    return status, error_json(type(exc).__name__, _message(exc), code=code, hint=hint,
                              exit_code=advice.exit_code)


def http_error_body(status: int, message: str) -> dict:
    """Fehlerkörper für einen HTTP-Status ohne eigene Ausnahme (Code nach Status)."""
    return error_json(_HTTP_KINDS.get(status, "HTTPFehler"), message, code=http_status_code(status))


def _location(loc) -> str:
    return ".".join(str(part) for part in loc)


_TYPE_TEXTS = (
    ("bool", N_("muss true oder false sein")),
    ("int", N_("muss eine ganze Zahl sein")),
    ("float", N_("muss eine Zahl sein")),
    ("string", N_("muss ein Text sein")),
    ("dict", N_("muss ein Objekt sein")),
    ("model", N_("muss ein Objekt sein")),
    ("list", N_("muss eine Liste sein")),
    ("json", N_("enthält kein gültiges JSON")),
)


def _type_text(error_type: str) -> str:
    for prefix, text in _TYPE_TEXTS:
        if error_type.startswith(prefix):
            return _t(text)
    return _t("ist ungültig")


def validation_body(errors: list[dict]) -> dict:
    places = [_location(err.get("loc", ())) for err in errors]
    first = errors[0] if errors else {}
    field = str(first.get("loc", ("?",))[-1]) if first.get("loc") else "?"
    if first.get("type") == "missing":
        message = _t("Ungültige Anfrage: Feld ‚{field}‘ fehlt", field=field)
    elif errors:
        message = _t("Ungültige Anfrage: Feld ‚{field}‘ {type_text}", field=field, type_text=_type_text(str(first.get('type', ''))))
    else:
        message = _t("Ungültige Anfrage")
    return error_json("Validierung", message, code="request.invalid", details={"errors": places})


def install_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def _validation(_request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(validation_body(list(exc.errors())), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        message = exc.detail if isinstance(exc.detail, str) else _t("Fehler")
        if exc.status_code == 404 and message == "Not Found":
            message = _t("Nicht gefunden")
        elif exc.status_code == 405 and message == "Method Not Allowed":
            message = _t("Methode nicht erlaubt")
        return JSONResponse(http_error_body(exc.status_code, message), status_code=exc.status_code,
                            headers=getattr(exc, "headers", None))

    async def _mapped(_request: Request, exc: Exception) -> JSONResponse:
        status, body = error_body(exc)
        return JSONResponse(body, status_code=status)

    for cls in _MAPPED:
        app.add_exception_handler(cls, _mapped)
    app.add_middleware(CatchAllMiddleware)


_MAPPED = (NotFound, TemplateError, DocumentError, ValueError, KeyError, ProtocolError, PrinterBusy,
           FileLockTimeout, ConnectTimeout, TransportError, IpcError)


class CatchAllMiddleware:
    """Unerwartete Ausnahmen -> 500 im Fehlerformat (ohne Traceback), statt sie an den Server
    weiterzureichen. Hat die Antwort schon begonnen (SSE), wird nur protokolliert."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def tracking_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception as exc:  # noqa: BLE001 (Fehlerformat statt Traceback)
            status, body = error_body(exc)
            if status == 500:
                log.exception("Unerwarteter Fehler in der Web-API", exc_info=exc)
            if started:
                return
            response = JSONResponse(body, status_code=status)
            await response(scope, receive, send)
