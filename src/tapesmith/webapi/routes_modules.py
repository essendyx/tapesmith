"""Routen /api/v1/modules und die Sperre der Routen ausgeschalteter Module.

`GET /modules` liefert die Modulbeschreibung aus `tapesmith.modules` mit dem Zustand je Modul,
`PUT /modules/{id}` schaltet ein Modul ein oder aus (wirkt sofort, ohne Neustart: jede Anfrage liest
config.json frisch). `module_gate` hängt als Abhängigkeit an jeder Route: gehört der Pfad zu einem
ausgeschalteten Modul, antwortet die API mit 409 und dem Fehlercode `module.disabled`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, StrictBool

from tapesmith import modules
from tapesmith.webapi.context import ApiContext, get_ctx
from tapesmith.webapi.errors import NotFound, error_json
from tapesmith.i18n import _t

router = APIRouter()


class ModuleBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool


def modules_json(cfg: dict) -> dict:
    enabled = modules.enabled_ids(cfg)
    data = modules.registry_json()
    for entry in data["modules"]:
        entry["enabled"] = entry["id"] in enabled
    data["enabled"] = list(enabled)
    return data


@router.get("/modules", summary="Module mit Beschreibung und Zustand")
def get_modules(ctx: ApiContext = Depends(get_ctx)) -> dict:
    return modules_json(ctx.config())


@router.put("/modules/{module_id}", summary="Modul ein- oder ausschalten")
def put_module(module_id: str, body: ModuleBody, ctx: ApiContext = Depends(get_ctx)) -> dict:
    if module_id not in modules.MODULE_IDS:
        raise NotFound(_t("Unbekanntes Modul '{module_id}'", module_id=module_id))
    modules.set_enabled(module_id, body.enabled)
    ctx.publish("config", {"keys": ["modules.enabled"]})
    return modules_json(ctx.config())


def module_gate(request: Request) -> None:
    """Abhängigkeit aller Routen: Routen ausgeschalteter Module sperren (`ModuleDisabled`)."""
    # Routenmuster (z. B. `/homelab/assets/{asset_id}/vault-note`); eingebundene Router kennen es
    # ohne das Präfix `/api/v1`.
    route = request.scope.get("route")
    path = getattr(route, "path", None) or request.url.path
    if not path.startswith(modules.API_PREFIX + "/") and request.url.path.startswith(modules.API_PREFIX + "/"):
        path = modules.API_PREFIX + path
    needed = modules.modules_for_api(path)
    if not needed:
        return
    ctx: ApiContext = request.app.state.ctx
    enabled = set(modules.enabled_ids(ctx.config()))
    for module_id in needed:
        if module_id not in enabled:
            raise modules.ModuleDisabled(module_id)


def install(app: FastAPI) -> None:
    """Fehlerantwort für `ModuleDisabled`: 409, Code `module.disabled`, Modul in `details`."""

    async def _disabled(_request: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, modules.ModuleDisabled)
        body = error_json("ModuleDisabled", str(exc), code=exc.code, hint=exc.hint,
                          details={"module": exc.module_id})
        return JSONResponse(body, status_code=exc.http_status)

    app.add_exception_handler(modules.ModuleDisabled, _disabled)
