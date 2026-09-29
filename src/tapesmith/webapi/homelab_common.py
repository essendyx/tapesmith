"""Gemeinsame API-Hilfen der Homelab-Routen.

Fehlerabbildung für `IntegrationError` (424/502/503), Ablage vorbereiteter Tabellen für den
Serien-Dialog der Seite Vorlagen und Zugriff auf injizierbare Fakes in `ctx.extras`.
"""

from __future__ import annotations

from collections.abc import Sequence

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from tapesmith.errors import error_code
from tapesmith.integrations import settings
from tapesmith.integrations.errors import IntegrationError
from tapesmith.webapi.actions import put_pending
from tapesmith.webapi.context import ApiContext
from tapesmith.webapi.errors import error_json

API_PREFIX = "/api/v1"


def integration_error_response(exc: IntegrationError) -> JSONResponse:
    """Fehlerantwort im API-Format mit Status `exc.http_status`."""
    body = error_json(type(exc).__name__, str(exc), code=error_code(exc), hint=exc.hint,
                      exit_code=exc.exit_code)
    return JSONResponse(body, status_code=exc.http_status)


def install_integration_handler(app: FastAPI) -> None:
    """Registriert den Handler für `IntegrationError` an der App."""

    async def _handler(_request: Request, exc: Exception) -> JSONResponse:
        return integration_error_response(exc)  # type: ignore[arg-type]

    app.add_exception_handler(IntegrationError, _handler)


def pending_table(ctx: ApiContext, headers: Sequence[str], rows: Sequence[Sequence[str]],
                  source_name: str) -> str:
    """Legt eine Tabelle für den Serien-Dialog ab und gibt ihre Kennung zurück."""
    entry = {"type": "table", "headers": [str(h) for h in headers],
             "rows": [["" if v is None else str(v) for v in row] for row in rows],
             "source_name": source_name}
    return put_pending(ctx, entry)


def load_homelab(ctx: ApiContext) -> dict:
    """Aktuelle Einstellungen aus `homelab.json`; ungültig: ValueError (422)."""
    return settings.load_settings()


def keyring_for(ctx: ApiContext):
    """Keyring-Modul aus `ctx.extras` (Tests setzen einen Fake), sonst None."""
    return ctx.extras.get("keyring_module")


def transport_for(ctx: ApiContext, service: str):
    """httpx-Transport für einen Dienst aus `ctx.extras["transports"]` (Tests), sonst None."""
    return (ctx.extras.get("transports") or {}).get(service)
