"""Routen /api/v1/homelab (Einstellungen und Prüfung).

`GET/PATCH /homelab/settings` liefert bzw. ändert `homelab.json` (öffentliche Sicht ohne Token-Werte),
`GET /homelab/check` prüft je Dienst ohne Netz, ob er eingerichtet und das Token vorhanden ist.
Registriert wird der Router über `webapi.homelab_routers`.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from tapesmith.integrations import settings
from tapesmith.webapi.context import ApiContext, get_ctx
from tapesmith.webapi.errors import error_json
from tapesmith.webapi.homelab_common import keyring_for, load_homelab
from tapesmith.i18n import _t

router = APIRouter()


class PatchHomelabBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    changes: dict[str, Any]


def _settings_json(ctx: ApiContext, data: dict) -> dict:
    return {"settings": settings.public_view(data, keyring_module=keyring_for(ctx)),
            "path": str(settings.settings_path())}


def _invalid(errors: list[str]) -> JSONResponse:
    body = error_json("Validierung", "; ".join(errors), hint=_t("Werte korrigieren und erneut speichern"),
                      details={"errors": errors})
    return JSONResponse(body, status_code=422)


def _is_token_value(key: str) -> bool:
    name = key.rpartition(".")[2]
    return "token" in name.lower() and name != "token_ref"


@router.get("/homelab/settings")
def get_homelab_settings(ctx: ApiContext = Depends(get_ctx)) -> dict:
    return _settings_json(ctx, load_homelab(ctx))


@router.patch("/homelab/settings")
def patch_homelab_settings(body: PatchHomelabBody, ctx: ApiContext = Depends(get_ctx)):
    token_errors = [_t("homelab.json: '{key}' ist nicht erlaubt: Token-Werte gehören nicht in die Einstellungen, nur Referenzen (token_ref)", key=key)
                    for key in body.changes if _is_token_value(key)]
    if token_errors:
        return _invalid(token_errors)
    try:
        data = settings.update_settings(body.changes)
    except settings.SettingsError as exc:
        return _invalid(exc.errors)
    if body.changes:
        ctx.publish("homelab", {"keys": list(body.changes)})
    return _settings_json(ctx, data)


@router.get("/homelab/check")
def get_homelab_check(ctx: ApiContext = Depends(get_ctx)) -> dict:
    data = load_homelab(ctx)
    return {"services": settings.check_services(data, keyring_module=keyring_for(ctx))}
