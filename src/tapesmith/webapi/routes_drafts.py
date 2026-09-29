"""Routen der Entwürfe: nur Rolle `admin` bzw. Sitzung.

`webapi/access.py` nennt `/drafts` nicht in der Positivliste, deshalb bekommen `drucken` und
`familie` 403. Der Store liegt je App in `ctx.extras["draft_store"]` (Tests setzen einen eigenen
mit falscher Uhr).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from tapesmith import paths
from tapesmith.webapi.context import ApiContext, get_ctx
from tapesmith.webapi.drafts import ALIVE_S, DRAFTS_DIR_NAME, DraftStore

router = APIRouter()


class PutBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    session: str
    title: Any = ""
    doc_name: Any = None
    document: Any
    dirty: Any = False
    order: Any = 0


class SessionBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    session: str


def draft_store(ctx: ApiContext) -> DraftStore:
    store = ctx.extras.get("draft_store")
    if store is None:
        store = ctx.extras.setdefault("draft_store", DraftStore(paths.app_dir() / DRAFTS_DIR_NAME))
    return store


@router.get("/drafts")
def list_drafts(session: str, ctx: ApiContext = Depends(get_ctx)) -> dict:
    return draft_store(ctx).list(session)


@router.post("/drafts/heartbeat")
def heartbeat(body: SessionBody, ctx: ApiContext = Depends(get_ctx)) -> dict:
    store = draft_store(ctx)
    store.heartbeat(body.session)
    return {"alive_s": ALIVE_S}


@router.get("/drafts/{draft_id}")
def get_draft(draft_id: str, ctx: ApiContext = Depends(get_ctx)) -> dict:
    return draft_store(ctx).get(draft_id)


@router.put("/drafts/{draft_id}")
def put_draft(draft_id: str, body: PutBody, ctx: ApiContext = Depends(get_ctx)) -> dict:
    return draft_store(ctx).put(draft_id, body.model_dump())


@router.delete("/drafts/{draft_id}")
def delete_draft(draft_id: str, ctx: ApiContext = Depends(get_ctx)) -> dict:
    draft_store(ctx).delete(draft_id)
    return {}


@router.post("/drafts/{draft_id}/adopt")
def adopt_draft(draft_id: str, body: SessionBody, ctx: ApiContext = Depends(get_ctx)) -> dict:
    return draft_store(ctx).adopt(draft_id, body.session)
