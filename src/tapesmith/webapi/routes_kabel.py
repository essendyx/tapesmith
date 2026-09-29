"""Routen `/api/v1/homelab/kabel`: NetBox-CSV-Import, TIA-606-ID-Schema und
Kabel-Register. Registriert wird der Router über `webapi.homelab_routers`.

`/kabel/netbox` verbraucht bewusst keine Nummern (reine Vorschau mit Platzhaltern "neu 1", "neu 2"
…); erst `/kabel/table` vergibt sie wirklich und trägt optional ins Register ein.
"""

from __future__ import annotations

import base64
import binascii
import dataclasses

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from tapesmith import numbering
from tapesmith.dataimport.mapping import MappingStore
from tapesmith.integrations import netbox, settings, tia606
from tapesmith.webapi.context import ApiContext, get_ctx
from tapesmith.webapi.homelab_common import load_homelab, pending_table
from tapesmith.i18n import _t

router = APIRouter()

MAX_CSV_BYTES = 2 * 1024 * 1024


def _decode_csv(csv_b64: str) -> bytes:
    try:
        data = base64.b64decode(csv_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(_t("CSV ist kein gültiges Base64: {exc}", exc=exc)) from exc
    if len(data) > MAX_CSV_BYTES:
        raise ValueError(_t("CSV zu groß (max. {value} MB)", value=MAX_CSV_BYTES // (1024 * 1024)))
    return data


def _placeholder_ids(n: int) -> list[str]:
    return [f"neu {i + 1}" for i in range(n)]


def _batch_duplicates(ids: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for kabel_id in ids:
        key = kabel_id.casefold()
        if key in seen:
            if kabel_id not in result:
                result.append(kabel_id)
        else:
            seen.add(key)
    return result


def _mapping_json(mapping: dict[str, str | list[str]]) -> dict[str, str | list[str]]:
    return {fid: (col if isinstance(col, str) else list(col)) for fid, col in mapping.items()}


def _row_json(row: netbox.CableRow) -> dict:
    return dataclasses.asdict(row)


class NetboxPreviewBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    csv_b64: str
    mapping: dict[str, str | list[str]] | None = None
    assign_ids: bool = False
    save_mapping: bool = False


class NetboxTableBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    csv_b64: str
    mapping: dict[str, str | list[str]] | None = None
    assign_ids: bool = False
    template: str = "kabelfahne"
    register_: bool = Field(default=False, alias="register")


class PortRangeBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    rack: str
    units: str
    ports: str


class IdsBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    mode: str
    pattern: str | None = None
    ranges: list[PortRangeBody] | None = None
    count: int | None = None
    register_: bool = Field(default=False, alias="register")
    table: bool = False


@router.post("/homelab/kabel/netbox")
def post_kabel_netbox(body: NetboxPreviewBody, ctx: ApiContext = Depends(get_ctx)) -> dict:
    data = _decode_csv(body.csv_b64)
    table = netbox.read_export(data)
    store = MappingStore()
    mapping = body.mapping or netbox.suggest_mapping(table, store)
    register = tia606.KabelRegister()
    new_id = _placeholder_ids if body.assign_ids else None
    result = netbox.build_rows(table, mapping, register=register, new_id=new_id)
    if body.save_mapping:
        netbox.save_mapping(store, table, mapping)
    return {
        "headers": list(result.headers),
        "mapping": _mapping_json(result.mapping),
        "rows": [_row_json(r) for r in result.rows],
        "duplicates": list(result.duplicates),
        "warnings": list(result.warnings),
        "preview_only": True,
    }


@router.post("/homelab/kabel/table")
def post_kabel_table(body: NetboxTableBody, ctx: ApiContext = Depends(get_ctx)) -> dict:
    data = _decode_csv(body.csv_b64)
    table = netbox.read_export(data)
    store = MappingStore()
    mapping = body.mapping or netbox.suggest_mapping(table, store)
    homelab = load_homelab(ctx)
    register = tia606.KabelRegister()
    ranges = numbering.NumberRanges()

    def _new_id(n: int) -> list[str]:
        return tia606.free_ids(ranges, homelab, n)

    result = netbox.build_rows(table, mapping, register=register,
                               new_id=_new_id if body.assign_ids else None)

    if body.register_:
        all_ids = [r.kabel_id for r in result.rows if r.kabel_id]
        batch_dupes = _batch_duplicates(all_ids)
        if batch_dupes:
            raise ValueError(_t("Kabel-ID mehrfach im Import: {items}", items=', '.join(batch_dupes)))
        entries = [
            tia606.KabelEntry(id=r.kabel_id, quelle=r.quelle, ziel=r.ziel, kabeltyp=r.kabeltyp,
                              quelle_import="netbox", created=ctx.now().isoformat(timespec="seconds"))
            for r in result.rows if r.kabel_id
        ]
        register.add(entries, allow_existing=True)

    headers, rows = netbox.template_rows(result.rows)
    pending_id = pending_table(ctx, headers, rows, "NetBox-Import")
    return {
        "pending_id": pending_id,
        "template": body.template,
        "count": len(result.rows),
        "new_ids": [r.kabel_id for r in result.rows if r.neu],
        "duplicates": list(result.duplicates),
        "warnings": list(result.warnings),
    }


@router.post("/homelab/kabel/ids")
def post_kabel_ids(body: IdsBody, ctx: ApiContext = Depends(get_ctx)) -> dict:
    homelab = load_homelab(ctx)
    register = tia606.KabelRegister()

    if body.mode == "schema":
        pattern = body.pattern or settings.setting(homelab, "kabel.tia_pattern")
        port_ranges = [
            tia606.PortRange(rack=r.rack, units=tia606.parse_numbers(r.units), ports=tia606.parse_numbers(r.ports))
            for r in (body.ranges or [])
        ]
        if not port_ranges:
            raise ValueError(_t("Mindestens ein Bereich (rack, units, ports) nötig"))
        ids = tia606.generate(pattern, port_ranges)
        quelle_import = "schema"
    elif body.mode == "frei":
        if not body.count:
            raise ValueError(_t("'count' muss 1..500 sein"))
        ranges = numbering.NumberRanges()
        ids = tia606.free_ids(ranges, homelab, body.count)
        quelle_import = "frei"
    else:
        raise ValueError(_t("Unbekannter Modus '{mode}' (erlaubt: schema, frei)", mode=body.mode))

    duplicates = register.duplicates(ids)
    if body.register_:
        if duplicates:
            raise ValueError(_t("Kabel-ID bereits vergeben: {items}", items=', '.join(duplicates)))
        entries = [
            tia606.KabelEntry(id=i, quelle="", ziel="", kabeltyp="", quelle_import=quelle_import,
                              created=ctx.now().isoformat(timespec="seconds"))
            for i in ids
        ]
        register.add(entries)

    pending_id = None
    if body.table:
        pending_id = pending_table(ctx, ["kabel_id"], [[i] for i in ids], _t("Kabel-ID-Schema"))

    return {"ids": ids, "duplicates": duplicates, "pending_id": pending_id}


@router.get("/homelab/kabel/register")
def get_kabel_register(query: str = "", ctx: ApiContext = Depends(get_ctx)) -> dict:
    register = tia606.KabelRegister()
    entries = register.all()
    if query:
        needle = query.casefold()
        entries = [
            e for e in entries
            if needle in e.id.casefold() or needle in e.quelle.casefold()
            or needle in e.ziel.casefold() or needle in e.kabeltyp.casefold()
        ]
    return {"entries": [dataclasses.asdict(e) for e in entries]}


@router.delete("/homelab/kabel/register/{kabel_id}")
def delete_kabel_register(kabel_id: str, ctx: ApiContext = Depends(get_ctx)) -> dict:
    register = tia606.KabelRegister()
    return {"removed": register.remove(kabel_id)}
