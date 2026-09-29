"""Routen /api/v1/homelab/assets (Client des Kurz-Link-Dienstes).

Register mit zentralem Nummernkreis `asset`, Kurz-Link-Kopplung über `integrations.assets`
und `integrations.shortlink`. Drucken läuft über die vorhandenen Endpunkte `/labels/render` bzw.
`/labels/print` (Einzeldruck) und den Serien-Dialog der Seite Vorlagen (`/table`). Registriert
wird der Router über `webapi.homelab_routers`.
"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict

from tapesmith import numbering
from tapesmith.integrations import shortlink
from tapesmith.integrations.assets import AssetStore, asset_link, label_values, peek_next_ids
from tapesmith.integrations.errors import IntegrationError
from tapesmith.webapi.context import ApiContext, get_ctx
from tapesmith.webapi.errors import NotFound
from tapesmith.webapi.homelab_common import keyring_for, load_homelab, pending_table, transport_for
from tapesmith.i18n import _t

router = APIRouter()

TABLE_HEADERS = ("nummer", "bezeichnung", "link")


class AssetCreateBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    count: int = 1
    bezeichnung: str = ""
    kategorie: str = ""
    standort: str = ""
    seriennummer: str = ""
    host: str = ""
    ziel: str | None = None
    paperless_doc: int | None = None
    notiz: str = ""


class AssetImportBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    bezeichnung: str = ""
    kategorie: str = ""
    standort: str = ""
    seriennummer: str = ""
    host: str = ""
    ziel: str | None = None
    paperless_doc: int | None = None
    notiz: str = ""


class AssetUpdateBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    bezeichnung: str | None = None
    kategorie: str | None = None
    standort: str | None = None
    seriennummer: str | None = None
    host: str | None = None
    ziel: str | None = None
    paperless_doc: int | None = None
    notiz: str | None = None


class AssetVoidBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    reason: str


class AssetTableBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    ids: list[str]


def _store(ctx: ApiContext) -> AssetStore:
    return AssetStore(clock=ctx.now)


def _ranges(ctx: ApiContext) -> numbering.NumberRanges:
    cfg = ctx.config()
    return numbering.NumberRanges(numbering.numbering_dir(cfg) / numbering.FILE_NAME)


def _link_kwargs(ctx: ApiContext) -> dict:
    return {"keyring_module": keyring_for(ctx), "transport": transport_for(ctx, "shortlink")}


def _ensure_links(ctx: ApiContext, data: dict, assets) -> list[str]:
    """Kurz-Links neuer Assets im Dienst anlegen (vorhandene Ziele bleiben), damit der später über
    `/label` gedruckte QR nicht ins Leere zeigt. Fehler des Dienstes werden zu Warnungen."""
    if not shortlink.configured(data):
        return []
    warnings: list[str] = []
    for asset in assets:
        try:
            asset_link(data, asset, **_link_kwargs(ctx))
        except IntegrationError as exc:
            warnings.append(_t("Kurz-Link für {id} nicht angelegt: {exc}", id=asset.id, exc=exc))
    return warnings


def _asset_json(asset) -> dict:
    return asdict(asset)


@router.get("/homelab/assets")
def assets_list(status: str | None = None, query: str = "", ctx: ApiContext = Depends(get_ctx)) -> dict:
    data = load_homelab(ctx)
    cfg = data["assets"]
    with _store(ctx) as store:
        assets = store.list(status=status, query=query)
    ranges = _ranges(ctx)
    next_id = peek_next_ids(ranges, data, 1)[0]
    return {
        "assets": [_asset_json(a) for a in assets],
        "range": {"prefix": cfg["prefix"], "width": cfg["width"], "next": next_id,
                  "check_digit": bool(cfg.get("check_digit", False))},
        "shortlink": shortlink.configured(data),
    }


@router.post("/homelab/assets")
def assets_create(body: AssetCreateBody, ctx: ApiContext = Depends(get_ctx)) -> dict:
    data = load_homelab(ctx)
    ranges = _ranges(ctx)
    with _store(ctx) as store:
        assets = store.reserve(ranges, data, body.count, bezeichnung=body.bezeichnung,
                               kategorie=body.kategorie, standort=body.standort,
                               seriennummer=body.seriennummer, host=body.host, ziel=body.ziel,
                               paperless_doc=body.paperless_doc, notiz=body.notiz)
    warnings = _ensure_links(ctx, data, assets)
    return {"assets": [_asset_json(a) for a in assets], "warnings": warnings}


@router.post("/homelab/assets/import")
def assets_import(body: AssetImportBody, ctx: ApiContext = Depends(get_ctx)) -> dict:
    data = load_homelab(ctx)
    with _store(ctx) as store:
        asset = store.add_existing(body.id, bezeichnung=body.bezeichnung, kategorie=body.kategorie,
                                   standort=body.standort, seriennummer=body.seriennummer,
                                   host=body.host, ziel=body.ziel, paperless_doc=body.paperless_doc,
                                   notiz=body.notiz)
    return {**_asset_json(asset), "warnings": _ensure_links(ctx, data, [asset])}


@router.put("/homelab/assets/{asset_id}")
def assets_update(asset_id: str, body: AssetUpdateBody, ctx: ApiContext = Depends(get_ctx)) -> dict:
    data = load_homelab(ctx)
    changes = body.model_dump(exclude_unset=True)
    warnings: list[str] = []
    with _store(ctx) as store:
        if store.get(asset_id) is None:
            raise NotFound(_t("Asset {asset_id!r} gibt es nicht", asset_id=asset_id))
        asset = store.update(asset_id, **changes)
        if "ziel" in changes and shortlink.configured(data):
            _link, w = asset_link(data, asset, **_link_kwargs(ctx))
            warnings.extend(w)
    return {**_asset_json(asset), "warnings": warnings}


@router.post("/homelab/assets/{asset_id}/void")
def assets_void(asset_id: str, body: AssetVoidBody, ctx: ApiContext = Depends(get_ctx)) -> dict:
    data = load_homelab(ctx)
    ranges = _ranges(ctx)
    with _store(ctx) as store:
        if store.get(asset_id) is None:
            raise NotFound(_t("Asset {asset_id!r} gibt es nicht", asset_id=asset_id))
        asset = store.void(ranges, data, asset_id, body.reason)
    return _asset_json(asset)


@router.get("/homelab/assets/{asset_id}/label")
def assets_label(asset_id: str, ctx: ApiContext = Depends(get_ctx)) -> dict:
    data = load_homelab(ctx)
    with _store(ctx) as store:
        asset = store.get(asset_id)
        if asset is None:
            raise NotFound(_t("Asset {asset_id!r} gibt es nicht", asset_id=asset_id))
        link, warnings = asset_link(data, asset, sync=False)
    return {"template": "asset-kurz", "values": label_values(asset, link), "warnings": warnings}


@router.post("/homelab/assets/table")
def assets_table(body: AssetTableBody, ctx: ApiContext = Depends(get_ctx)) -> dict:
    data = load_homelab(ctx)
    rows: list[list[str]] = []
    missing: list[str] = []
    warnings: list[str] = []
    with _store(ctx) as store:
        for asset_id in body.ids:
            asset = store.get(asset_id)
            if asset is None:
                missing.append(asset_id)
                continue
            link, w = asset_link(data, asset, **_link_kwargs(ctx))
            warnings.extend(w)
            rows.append([asset.id, asset.bezeichnung, link])
    if missing:
        raise NotFound(_t("Unbekannte Assets: {items}", items=', '.join(missing)))
    pending_id = pending_table(ctx, list(TABLE_HEADERS), rows, "Assets")
    return {"pending_id": pending_id, "template": "asset-kurz", "count": len(rows), "warnings": warnings}


@router.get("/homelab/assets/export.csv")
def assets_export_csv(ctx: ApiContext = Depends(get_ctx)) -> Response:
    with _store(ctx) as store:
        csv_text = store.export_csv()
    return Response(content=csv_text, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="assets.csv"'})
