"""Kern-Endpunkte: Health, App-Info, Status, Abbruch, Weiter, Verbindung, Ereignisse (SSE)."""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import AsyncIterator, Callable

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, StrictBool

import tapesmith
from tapesmith import i18n, modules
from tapesmith.config import gui_setting, setting
from tapesmith.webapi import access
from tapesmith.webapi.context import ApiContext, get_ctx
from tapesmith.webapi.convert import profile_json, status_json, tape_json
from tapesmith.webapi.events import Subscription, sse_format

PING_S = 15.0
PING = ": ping\n\n"

health_router = APIRouter()
router = APIRouter()


class RefreshBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    quick: StrictBool = False
    reconnect: StrictBool = False


class CancelBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    job_key: str


class EmptyBody(BaseModel):
    model_config = ConfigDict(extra="ignore")


@health_router.get("/health")
def health(request: Request, ctx: ApiContext = Depends(get_ctx)):
    """Loopback bekommt `home_key` und `pid` dazu, LAN-Clients nur `ok`, `app`, `version`."""
    ok = not ctx.service.closed
    body = {"ok": ok, "app": "tapesmith", "version": tapesmith.__version__}
    if access.principal(request).loopback:
        body.update(home_key=ctx.home_key, pid=os.getpid())
    return JSONResponse(body, status_code=200 if ok else 503)


@router.get("/app")
def app_info(ctx: ApiContext = Depends(get_ctx)) -> dict:
    cfg = ctx.config()
    tape = ctx.tape()
    return {
        "version": tapesmith.__version__,
        "home_key": ctx.home_key,
        "pid": os.getpid(),
        "port": ctx.port,
        "accent": ctx.accent_reader(),
        "profile": profile_json(ctx.profile()),
        "tape": tape_json(tape, tape.id),
        "screen_px_per_mm": gui_setting(cfg, "screen_px_per_mm"),
        "ctrl_enter_only": bool(gui_setting(cfg, "ctrl_enter_only")),
        "language": setting(cfg, "app.language"),
        # Wirksame Sprache des Dienstes (TAPESMITH_LANG, app.language, sonst Windows-Anzeigesprache);
        # die Oberfläche folgt ihr bei "auto" statt der Browsersprache.
        "resolved_language": i18n.current_language(cfg),
        "system_language": i18n.system_language(),
        "theme": setting(cfg, "app.theme"),
        "modules": list(modules.enabled_ids(cfg)),
    }


def _status(ctx: ApiContext, report) -> dict:
    return status_json(report, now=ctx.now(), mac=ctx.config().get("mac"))


@router.get("/status")
def status(ctx: ApiContext = Depends(get_ctx)) -> dict:
    return _status(ctx, ctx.service.status(fresh=False))


@router.post("/status/refresh")
def status_refresh(body: RefreshBody | None = None, ctx: ApiContext = Depends(get_ctx)) -> dict:
    quick = body.quick if body is not None else False
    if body is not None and body.reconnect:
        return _status(ctx, ctx.service.status(fresh=True, reconnect=True))
    return _status(ctx, ctx.service.status(quick=quick, fresh=True))


@router.post("/print/cancel")
def print_cancel(body: CancelBody, ctx: ApiContext = Depends(get_ctx)) -> dict:
    return {"cancelled": bool(ctx.service.cancel(body.job_key))}


@router.post("/print/continue")
def print_continue(body: EmptyBody | None = None, ctx: ApiContext = Depends(get_ctx)) -> dict:
    return {"was_pausing": bool(ctx.service.continue_cut())}


@router.post("/connection/preconnect")
def connection_preconnect(body: EmptyBody | None = None, ctx: ApiContext = Depends(get_ctx)) -> dict:
    ctx.service.preconnect()
    return {}


@router.post("/connection/disconnect")
def connection_disconnect(body: EmptyBody | None = None, ctx: ApiContext = Depends(get_ctx)) -> dict:
    ctx.service.disconnect()
    return {}


async def event_stream(request, sub: Subscription, *, hello: dict, limit: int | None,
                       wait_s: float = 1.0, ping_s: float = PING_S,
                       clock: Callable[[], float] = time.monotonic) -> AsyncIterator[str]:
    """SSE-Strom: erst `hello`, dann Ereignisse; `: ping` bei Ruhe alle `ping_s`. Ende bei
    Verbindungsabbruch, beendetem Abo oder erreichtem `limit` (ohne `hello`)."""
    sent = 0
    try:
        yield sse_format("hello", hello)
        last = clock()
        while limit is None or sent < limit:
            if await request.is_disconnected():
                break
            item = await asyncio.to_thread(sub.get, wait_s)
            if item is None:
                if sub.closed:
                    break
                if clock() - last >= ping_s:
                    last = clock()
                    yield PING
                continue
            yield sse_format(*item)
            sent += 1
            last = clock()
    finally:
        sub.close()


@router.get("/events")
async def events(request: Request, limit: int | None = None):
    ctx: ApiContext = request.app.state.ctx
    sub = ctx.broker.subscribe()
    hello = {"version": tapesmith.__version__, "home_key": ctx.home_key}
    stream = event_stream(request, sub, hello=hello, limit=limit)
    return StreamingResponse(stream, media_type="text/event-stream",
                             headers={"X-Accel-Buffering": "no"})
