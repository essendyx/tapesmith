"""Routen /api/v1/homelab/paperless (ASN-Serien, Garantie-Etikett).

Nur lesende Paperless-Aufrufe. Registriert wird der Router über `webapi.homelab_routers`.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from tapesmith import numbering
from tapesmith.integrations import paperless, settings, shortlink
from tapesmith.webapi.context import ApiContext, get_ctx
from tapesmith.webapi.homelab_common import keyring_for, load_homelab, pending_table, transport_for
from tapesmith.i18n import _t

router = APIRouter()


class ReserveBody(BaseModel):
    count: int


class VoidBody(BaseModel):
    asn: str
    reason: str


def _ranges(ctx: ApiContext) -> numbering.NumberRanges:
    return numbering.NumberRanges(numbering.numbering_dir(ctx.config()) / numbering.FILE_NAME)


def _client(ctx: ApiContext, data: dict) -> paperless.PaperlessClient:
    return paperless.PaperlessClient.from_settings(data, keyring_module=keyring_for(ctx),
                                                    transport=transport_for(ctx, "paperless"))


def _hit_json(hit: paperless.DocumentHit) -> dict:
    return {"id": hit.id, "title": hit.title, "created": hit.created, "correspondent": hit.correspondent,
            "asn": hit.asn, "custom": hit.custom, "url": hit.url}


def _warranty_json(w: paperless.Warranty) -> dict:
    return {"document": _hit_json(w.document), "kaufdatum": w.kaufdatum, "monate": w.monate,
            "ende": w.ende, "quelle": w.quelle, "quelle_ende": w.quelle_ende}


@router.get("/homelab/paperless/asn/next")
def get_asn_next(ctx: ApiContext = Depends(get_ctx)) -> dict:
    data = load_homelab(ctx)
    ranges = _ranges(ctx)
    section = data["paperless"]
    with _client(ctx, data) as client:
        paperless_next = client.next_asn()
    try:
        local_next = ranges.peek(section["asn_range"])
    except KeyError:
        local_next = None
    next_text = paperless.peek_next_asn(ranges, data, paperless_next)
    return {"paperless_next": paperless_next, "local_next": local_next, "next": next_text,
            "prefix": section["asn_prefix"], "width": section["asn_width"], "hint": paperless.SCAN_TEST_HINT}


@router.post("/homelab/paperless/asn/reserve")
def post_asn_reserve(body: ReserveBody, ctx: ApiContext = Depends(get_ctx)) -> dict:
    data = load_homelab(ctx)
    ranges = _ranges(ctx)
    with _client(ctx, data) as client:
        numbers = paperless.reserve_asns(client, ranges, data, body.count)
    pending_id = pending_table(ctx, ["asn"], [[n] for n in numbers], "Paperless-ASN")
    return {"numbers": numbers, "pending_id": pending_id, "template": "asn", "hint": paperless.SCAN_TEST_HINT}


@router.post("/homelab/paperless/asn/void")
def post_asn_void(body: VoidBody, ctx: ApiContext = Depends(get_ctx)) -> dict:
    data = load_homelab(ctx)
    ranges = _ranges(ctx)
    paperless.void_asn(ranges, data, body.asn, body.reason)
    return {"ok": True}


@router.get("/homelab/paperless/documents")
def get_documents(query: str = "", correspondent: str = "", date_from: str = "", date_to: str = "",
                  limit: int = 25, ctx: ApiContext = Depends(get_ctx)) -> dict:
    data = load_homelab(ctx)
    from_date = date.fromisoformat(date_from) if date_from else None
    to_date = date.fromisoformat(date_to) if date_to else None
    with _client(ctx, data) as client:
        hits = client.search(query, correspondent=correspondent, date_from=from_date, date_to=to_date,
                             limit=limit)
    return {"documents": [_hit_json(h) for h in hits]}


@router.get("/homelab/paperless/documents/{doc_id}/warranty")
def get_warranty(doc_id: int, months: int | None = None, geraet: str = "",
                 ctx: ApiContext = Depends(get_ctx)) -> dict:
    data = load_homelab(ctx)
    with _client(ctx, data) as client:
        hit = client.document(doc_id)
    w = paperless.warranty(hit, data["paperless"]["warranty_fields"], months=months)

    warnings: list[str] = []
    if shortlink.configured(data):
        link = shortlink.link_for(data, f"DOC-{doc_id}", hit.url, note=hit.title,
                                  keyring_module=keyring_for(ctx), transport=transport_for(ctx, "shortlink"))
    else:
        link = hit.url
        warnings.append(_t("QR enthält die lange Paperless-Adresse"))

    geraet_value = geraet or hit.title[:20]
    values, value_warnings = paperless.warranty_values(w, geraet=geraet_value, link=link)

    return {"warranty": _warranty_json(w), "label": {"template": "garantie-qr", "values": values},
            "warnings": value_warnings + warnings}
