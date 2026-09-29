"""Update-Routen, nur Rolle `admin` bzw. Sitzung.

`GET /update/status`, `POST /update/check`, `POST /update/install` (202, Bereitstellung und Start
laufen im Hintergrund, Fortschritt über `status`), `POST /update/rollback` (202). Installation und
Rückstellung verlangen „kein Auftrag aktiv, Warteschlange leer“ (sonst 409 `update.busy`), die
Oberfläche fragt vorher, weil der Dienst neu startet (die Oberfläche öffnet sich danach auf
`reopen_route` in einem neuen Browser-Tab). `UpdateError` wird zum Fehlerformat mit
seinem Code und Status."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, StrictStr

from tapesmith.update.errors import UpdateError
from tapesmith.update.service import UpdateService
from tapesmith.webapi.context import ApiContext, get_ctx
from tapesmith.webapi.errors import error_json
from tapesmith.i18n import _t

log = logging.getLogger(__name__)

router = APIRouter()


class InstallBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    version: StrictStr
    reopen_route: StrictStr | None = None


class RollbackBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    reopen_route: StrictStr | None = None


def update_service(ctx: ApiContext) -> UpdateService:
    service = ctx.extras.get("update_service")
    if service is None:
        service = ctx.extras.setdefault("update_service", UpdateService(ctx.config))
    return service


def _runner(ctx: ApiContext) -> Callable[[Callable[[], None]], None]:
    runner = ctx.extras.get("update_runner")
    if runner is not None:
        return runner

    def start(fn: Callable[[], None]) -> None:
        threading.Thread(target=fn, name="p12-update-install", daemon=True).start()

    return start


def safe_route(route: str | None) -> str | None:
    """Nur relative Pfade der Oberfläche (`/…`, ohne Leerraum, höchstens 500 Zeichen), sonst None."""
    if not route or not route.startswith("/") or route.startswith("//") or len(route) > 500:
        return None
    if any(ch.isspace() for ch in route):
        return None
    return route


def _error(exc: UpdateError) -> JSONResponse:
    return JSONResponse(error_json(type(exc).__name__, str(exc), code=exc.code, hint=exc.hint),
                        status_code=exc.http_status)


def _check_idle(ctx: ApiContext) -> None:
    busy = ctx.service.busy()
    if not busy:
        try:
            busy = ctx.service.queue.active_count() > 0
        except Exception:  # noqa: BLE001
            busy = False
    if busy:
        raise UpdateError("update.busy", _t("Es läuft ein Druckauftrag bzw. die Warteschlange ist nicht leer"),
                          hint=_t("Nach dem Druck erneut versuchen."))


@router.get("/update/status")
def update_status(ctx: ApiContext = Depends(get_ctx)):
    return update_service(ctx).status(ctx.service).to_json()


@router.post("/update/check")
def update_check(ctx: ApiContext = Depends(get_ctx)):
    try:
        return update_service(ctx).check(ctx.service).to_json()
    except UpdateError as exc:
        return _error(exc)


@router.post("/update/install", status_code=202)
def update_install(body: InstallBody, ctx: ApiContext = Depends(get_ctx)):
    svc = update_service(ctx)
    try:
        _check_idle(ctx)
        if not svc.installed():
            from tapesmith.update.service import NOT_INSTALLED_MESSAGE

            raise UpdateError("update.not_installed", _t(NOT_INSTALLED_MESSAGE))
        lock = ctx.extras.setdefault("update_lock", threading.Lock())
        if not lock.acquire(blocking=False):
            raise UpdateError("update.busy", _t("Ein Update wird bereits vorbereitet"))
    except UpdateError as exc:
        return _error(exc)

    def work() -> None:
        try:
            svc.prepare(body.version)
            svc.start_install(body.version, reopen_route=safe_route(body.reopen_route))
        except UpdateError as exc:
            log.warning("Update %s nicht gestartet: %s", body.version, exc)
        except Exception:  # noqa: BLE001
            log.exception("Update %s: unerwarteter Fehler", body.version)
        finally:
            lock.release()

    _runner(ctx)(work)
    return JSONResponse({"started": True}, status_code=202)


@router.post("/update/rollback", status_code=202)
def update_rollback(body: RollbackBody | None = None, ctx: ApiContext = Depends(get_ctx)):
    svc = update_service(ctx)
    try:
        _check_idle(ctx)
        svc.start_rollback(reopen_route=safe_route(body.reopen_route) if body is not None else None)
    except UpdateError as exc:
        return _error(exc)
    return JSONResponse({"started": True}, status_code=202)
