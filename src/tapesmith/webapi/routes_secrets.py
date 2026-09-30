"""Routen /api/v1/secrets: Geheimwerte aller Dienste setzen, übernehmen, entfernen.

Nur Rolle `admin`. Die Antworten nennen je Slot nur Quelle und Zustand, nie den Wert und nie den
Pfad einer externen Quelle (`tapesmith.secretslots`).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from tapesmith import secretslots
from tapesmith.i18n import _t
from tapesmith.webapi.access import require_role
from tapesmith.webapi.context import ApiContext, get_ctx
from tapesmith.webapi.errors import NotFound

router = APIRouter(dependencies=[Depends(require_role("admin"))])


class SecretValueBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    value: str


def _keyring(ctx: ApiContext):
    return ctx.extras.get("keyring_module") or ctx.extras.get("keyring")


def _call(ctx: ApiContext, slot_id: str, action, **kw) -> dict:
    try:
        result = action(slot_id, keyring_module=_keyring(ctx), environ=ctx.extras.get("environ"), **kw)
    except secretslots.SlotNotFound as exc:
        raise NotFound(_t("Geheimwert '{name}' unbekannt", name=slot_id)) from exc
    ctx.service.request_reload()
    ctx.publish("config", {"keys": [f"secrets.{slot_id}"]})
    ctx.publish("homelab", {"keys": [f"secrets.{slot_id}"]})
    return result


@router.get("/secrets", summary="Zustand aller Geheimwerte (ohne Werte)")
def get_secrets(ctx: ApiContext = Depends(get_ctx)) -> dict:
    return {"slots": secretslots.statuses(keyring_module=_keyring(ctx), environ=ctx.extras.get("environ"))}


@router.post("/secrets/adopt-all", summary="Alle externen Quellen in Tapesmith übernehmen")
def post_secrets_adopt_all(ctx: ApiContext = Depends(get_ctx)) -> dict:
    result = secretslots.adopt_all(keyring_module=_keyring(ctx), environ=ctx.extras.get("environ"))
    if result["adopted"]:
        ctx.service.request_reload()
        keys = [f"secrets.{slot_id}" for slot_id in result["adopted"]]
        ctx.publish("config", {"keys": keys})
        ctx.publish("homelab", {"keys": keys})
    return result


@router.put("/secrets/{slot_id}", summary="Geheimwert speichern (Windows-Anmeldeinformationen)")
def put_secret(slot_id: str, body: SecretValueBody, ctx: ApiContext = Depends(get_ctx)) -> dict:
    return _call(ctx, slot_id, secretslots.store, value=body.value)


@router.post("/secrets/{slot_id}/adopt", summary="Wert einer externen Quelle in Tapesmith übernehmen")
def post_secret_adopt(slot_id: str, ctx: ApiContext = Depends(get_ctx)) -> dict:
    return _call(ctx, slot_id, secretslots.adopt)


@router.delete("/secrets/{slot_id}", summary="Geheimwert entfernen")
def delete_secret(slot_id: str, ctx: ApiContext = Depends(get_ctx)) -> dict:
    return _call(ctx, slot_id, secretslots.remove)
