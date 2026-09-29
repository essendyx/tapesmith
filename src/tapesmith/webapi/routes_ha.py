"""Routen /api/v1/homelab/ha: Batteriestände aus Home Assistant, lokale Typzuordnung,
Serien-Tabelle für die Vorlage `batterie` und optionales HA-To-do. Registriert wird der Router
über `webapi.homelab_routers`."""

from __future__ import annotations

import dataclasses
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from tapesmith.integrations import homeassistant as ha
from tapesmith.integrations.errors import NotConfigured
from tapesmith.webapi.context import ApiContext, get_ctx
from tapesmith.webapi.homelab_common import keyring_for, load_homelab, pending_table, transport_for
from tapesmith.i18n import _t

router = APIRouter()

TABLE_HEADERS = ("geraet", "raum", "typ", "datum")


class BatteryTypeBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    entity_id: str
    battery_type: str | None = None


class TableBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    entity_ids: list[str]
    datum: str | None = None


class TodoBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    item: str = Field(min_length=1, max_length=120)
    due: str
    description: str = ""


def _device_json(dev: ha.BatteryDevice) -> dict:
    return dataclasses.asdict(dev)


def _client(ctx: ApiContext, data: dict) -> ha.HaClient:
    return ha.HaClient.from_settings(data, keyring_module=keyring_for(ctx),
                                     transport=transport_for(ctx, "homeassistant"))


@router.get("/homelab/ha/batteries")
def get_batteries(below: int | None = Query(default=None), ctx: ApiContext = Depends(get_ctx)) -> dict:
    data = load_homelab(ctx)
    ha_settings = data["homeassistant"]
    threshold = below if below is not None else ha_settings.get("battery_below", 101)
    client = _client(ctx, data)
    types = ha.BatteryTypes()
    raw = client.batteries()
    devices = ha.parse_devices(raw, types, below=threshold)
    return {"devices": [_device_json(d) for d in devices], "todo_entity": ha_settings.get("todo_entity"),
            "warnings": []}


@router.put("/homelab/ha/battery-type")
def put_battery_type(body: BatteryTypeBody, ctx: ApiContext = Depends(get_ctx)) -> dict:
    ha.BatteryTypes().set(body.entity_id, body.battery_type)
    return {"ok": True}


@router.post("/homelab/ha/table")
def post_table(body: TableBody, ctx: ApiContext = Depends(get_ctx)) -> dict:
    data = load_homelab(ctx)
    client = _client(ctx, data)
    types = ha.BatteryTypes()
    raw = client.batteries()
    by_id = {d.entity_id: d for d in ha.parse_devices(raw, types, below=101)}
    day = datetime.strptime(body.datum, "%Y-%m-%d").date() if body.datum else ctx.now().date()

    rows: list[list[str]] = []
    warnings: list[str] = []
    for entity_id in body.entity_ids:
        dev = by_id.get(entity_id)
        if dev is None:
            warnings.append(_t("Gerät '{entity_id}' nicht gefunden", entity_id=entity_id))
            continue
        values = ha.battery_values(dev, day=day)
        if not values["typ"]:
            warnings.append(_t("Gerät '{device}' hat keinen Batterietyp, Feld bleibt leer", device=dev.device))
        rows.append([values[h] for h in TABLE_HEADERS])

    pending_id = pending_table(ctx, TABLE_HEADERS, rows, _t("Home Assistant Batterien"))
    return {"pending_id": pending_id, "template": "batterie", "count": len(rows), "warnings": warnings}


@router.post("/homelab/ha/todo")
def post_todo(body: TodoBody, ctx: ApiContext = Depends(get_ctx)) -> dict:
    data = load_homelab(ctx)
    entity_id = data["homeassistant"].get("todo_entity")
    if not entity_id:
        raise NotConfigured("Home Assistant",
                            _t("To-do-Liste nicht eingerichtet: homeassistant.todo_entity fehlt"))
    client = _client(ctx, data)
    due = datetime.strptime(body.due, "%Y-%m-%d").date()
    client.add_todo(entity_id, body.item, due=due, description=body.description)
    return {"ok": True, "entity_id": entity_id}
