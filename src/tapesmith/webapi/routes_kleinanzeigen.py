"""Routen /api/v1/homelab/ka (Kleinanzeigen-Artikel-Tracking).

Registriert wird der Router über `webapi.homelab_routers`.
"""

from __future__ import annotations

import dataclasses
from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from tapesmith import numbering
from tapesmith.integrations import kleinanzeigen as ka
from tapesmith.integrations import shortlink
from tapesmith.integrations.errors import IntegrationError
from tapesmith.numbering import NumberRanges
from tapesmith.webapi.context import ApiContext, get_ctx
from tapesmith.webapi.errors import NotFound
from tapesmith.webapi.homelab_common import keyring_for, load_homelab, transport_for
from tapesmith.i18n import _t

router = APIRouter()


class NewArtikelBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    titel: str
    preis: str = ""
    anzeige: str | None = None
    ort: str = ""
    notiz: str = ""


class UpdateArtikelBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    titel: str | None = None
    preis: str | None = None
    anzeige: str | None = None
    ort: str | None = None
    notiz: str | None = None


class StatusBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    status: str
    name: str | None = None
    datum: str | None = None


def _ranges(ctx: ApiContext) -> NumberRanges:
    return NumberRanges(numbering.numbering_dir(ctx.config()) / numbering.FILE_NAME)


def _store(ctx: ApiContext) -> ka.KaStore:
    return ka.KaStore(clock=ctx.now)


def _json(art: ka.Artikel) -> dict:
    return dataclasses.asdict(art)


def _get_or_404(store: ka.KaStore, ka_id: str) -> ka.Artikel:
    art = store.get(ka_id)
    if art is None:
        raise NotFound(_t("Kleinanzeigen-Artikel '{ka_id}' gibt es nicht", ka_id=ka_id))
    return art


@router.get("/homelab/ka")
def list_artikel(status: str | None = None, query: str = "", ctx: ApiContext = Depends(get_ctx)) -> dict:
    data = load_homelab(ctx)
    with _store(ctx) as store:
        items = store.list(status=status, query=query)
    ranges = _ranges(ctx)
    ka.ensure_range(ranges, data)
    next_id = ranges.peek(data["kleinanzeigen"]["range"])
    return {"items": [_json(a) for a in items], "next": next_id, "shortlink": shortlink.configured(data)}


@router.post("/homelab/ka")
def create_artikel(body: NewArtikelBody, ctx: ApiContext = Depends(get_ctx)) -> dict:
    data = load_homelab(ctx)
    ranges = _ranges(ctx)
    with _store(ctx) as store:
        art = store.add(ranges, data, titel=body.titel, preis=body.preis, anzeige=body.anzeige,
                        ort=body.ort, notiz=body.notiz)
    warnings: list[str] = []
    if shortlink.configured(data):
        # Kurz-Link gleich anlegen, damit das später über /label gedruckte Etikett nicht ins Leere zeigt.
        try:
            ka.article_link(data, art, keyring_module=keyring_for(ctx),
                            transport=transport_for(ctx, "shortlink"))
        except IntegrationError as exc:
            warnings.append(_t("Kurz-Link für {id} nicht angelegt: {exc}", id=art.id, exc=exc))
    ctx.publish("kleinanzeigen", {"id": art.id})
    return {**_json(art), "warnings": warnings}


@router.put("/homelab/ka/{ka_id}")
def update_artikel(ka_id: str, body: UpdateArtikelBody, ctx: ApiContext = Depends(get_ctx)) -> dict:
    data = load_homelab(ctx)
    changes = body.model_dump(exclude_unset=True)
    with _store(ctx) as store:
        before = _get_or_404(store, ka_id)
        art = store.update(ka_id, **changes)
        if art.anzeige != before.anzeige and shortlink.configured(data):
            shortlink.link_for(data, art.id, art.anzeige, note=art.titel,
                               keyring_module=keyring_for(ctx), transport=transport_for(ctx, "shortlink"))
    ctx.publish("kleinanzeigen", {"id": art.id})
    return _json(art)


@router.post("/homelab/ka/{ka_id}/status")
def set_status(ka_id: str, body: StatusBody, ctx: ApiContext = Depends(get_ctx)) -> dict:
    if body.status not in ka.STATUSES:
        raise ValueError(_t("Unbekannter Status '{status}' (erlaubt: {items})", status=body.status, items=', '.join(ka.STATUSES)))
    with _store(ctx) as store:
        _get_or_404(store, ka_id)
        if body.status == "reserviert":
            if not body.name or not body.datum:
                raise ValueError(_t("Reservierung braucht Name und Datum"))
            art = store.reserve(ka_id, body.name, date.fromisoformat(body.datum))
        elif body.status == "verkauft":
            if not body.name:
                raise ValueError(_t("Verkauf braucht einen Namen"))
            on = date.fromisoformat(body.datum) if body.datum else ctx.now().date()
            art = store.sell(ka_id, body.name, on)
        else:
            art = store.release(ka_id)
    ctx.publish("kleinanzeigen", {"id": art.id, "status": art.status})
    return _json(art)


@router.get("/homelab/ka/{ka_id}/label")
def get_label(ka_id: str, art: str = "artikel", ctx: ApiContext = Depends(get_ctx)) -> dict:
    with _store(ctx) as store:
        artikel = _get_or_404(store, ka_id)
    if art == "reserviert":
        label = ka.reserved_label(artikel)
        return {**label, "warnings": []}
    data = load_homelab(ctx)
    label, warnings = ka.article_label(data, artikel, sync=False)
    return {**label, "warnings": warnings}
