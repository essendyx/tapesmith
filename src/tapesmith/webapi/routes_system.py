"""Routen /api/v1 (Bereich system): Windows-Integration, Aktionen/`pending`,
Sicherung, Konfiguration als Code.

Registrierungsreihenfolge verbindlich: feste Pfade vor Parameterpfaden (`/integration/install`,
`/uninstall`, `/resolve` vor `GET /integration/pending/{id}`; `POST /backups/restore` vor
etwaigen `/backups/{name}`-Pfaden)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, StrictBool

from tapesmith import backup as backup_mod
from tapesmith import configcode, integration
from tapesmith.errors import EXIT_BUSY
from tapesmith.webapi import actions
from tapesmith.webapi.context import ApiContext, get_ctx
from tapesmith.webapi.errors import NotFound, error_json
from tapesmith.i18n import N_, _t

router = APIRouter()

_RESTORE_HINT = N_("Erst ‚p12 daemon stop‘, dann ‚p12 backup restore {name}‘ in der Konsole")


class IntegrationChangeBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    context: bool = False
    uri: bool = False
    autostart: bool = False
    dry_run: bool = False


class ResolveBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    uri: str | None = None
    open: str | None = None
    path: str | None = None


class BackupCreateBody(BaseModel):
    model_config = ConfigDict(extra="ignore")


class BackupRestoreBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str
    dry_run: StrictBool = False


class ConfigExportBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    dir: str
    include_templates: StrictBool = True
    strip_secrets: StrictBool = False


class ConfigImportBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    dir: str
    dry_run: StrictBool = False
    include_templates: StrictBool = True


def _parts(body: IntegrationChangeBody) -> list[str]:
    parts = []
    if body.context:
        parts.append("context")
    if body.uri:
        parts.append("uri")
    if body.autostart:
        parts.append("autostart")
    if not parts:
        raise ValueError(_t("Bitte mindestens einen Teil wählen"))
    return parts


def _integration_json(backend, lines: list[str]) -> dict:
    return {"status": integration.status(backend), "lines": lines}


@router.get("/integration")
def integration_status(ctx: ApiContext = Depends(get_ctx)) -> dict:
    return _integration_json(ctx.registry_factory(), [])


@router.post("/integration/install")
def integration_install(body: IntegrationChangeBody, ctx: ApiContext = Depends(get_ctx)) -> dict:
    parts = _parts(body)
    backend = ctx.registry_factory()
    lines = integration.install(backend, parts, dry_run=body.dry_run)
    return _integration_json(backend, lines)


@router.post("/integration/uninstall")
def integration_uninstall(body: IntegrationChangeBody, ctx: ApiContext = Depends(get_ctx)) -> dict:
    parts = _parts(body)
    backend = ctx.registry_factory()
    lines = integration.uninstall(backend, parts, dry_run=body.dry_run)
    return _integration_json(backend, lines)


@router.post("/integration/resolve")
def integration_resolve(body: ResolveBody, ctx: ApiContext = Depends(get_ctx)) -> dict:
    return actions.resolve_action(ctx, uri=body.uri, open=body.open, path=body.path)


@router.get("/integration/pending/{pending_id}")
def integration_pending(pending_id: str, ctx: ApiContext = Depends(get_ctx)) -> dict:
    return actions.get_pending(ctx, pending_id)


def _backup_json(path: Path, created: datetime, size: int) -> dict:
    return {"name": path.name, "path": str(path), "created": created.isoformat(timespec="seconds"),
            "size_bytes": size}


@router.get("/backups")
def backups_list(ctx: ApiContext = Depends(get_ctx)) -> dict:
    cfg = ctx.config()
    directory = backup_mod.backup_dir(cfg)
    items = backup_mod.list_backups(directory)
    return {"dir": str(directory), "backups": [_backup_json(p, c, s) for p, c, s in items]}


@router.post("/backups")
def backups_create(body: BackupCreateBody | None = None, ctx: ApiContext = Depends(get_ctx)) -> dict:
    cfg = ctx.config()
    zip_path = backup_mod.create_backup(cfg=cfg)
    for path, created, size in backup_mod.list_backups(zip_path.parent):
        if path == zip_path:
            return _backup_json(path, created, size)
    stat = zip_path.stat()  # Sollte nie eintreten (gerade erst geschrieben); trotzdem robust.
    return _backup_json(zip_path, datetime.fromtimestamp(stat.st_mtime), stat.st_size)


@router.post("/backups/restore")
def backups_restore(body: BackupRestoreBody, ctx: ApiContext = Depends(get_ctx)) -> dict:
    cfg = ctx.config()
    directory = backup_mod.backup_dir(cfg)
    match = None
    for path, _created, _size in backup_mod.list_backups(directory):
        if path.name == body.name:
            match = path
            break
    if match is None:
        raise NotFound(_t("Sicherung '{name}' nicht gefunden", name=body.name))

    if body.dry_run:
        lines = backup_mod.restore_backup(match, dry_run=True)
        return {"lines": lines}

    message = _t(_RESTORE_HINT).format(name=body.name)
    return JSONResponse(error_json("Dienst läuft", message, exit_code=EXIT_BUSY), status_code=409)


@router.post("/config/export")
def config_export(body: ConfigExportBody, ctx: ApiContext = Depends(get_ctx)) -> dict:
    files = configcode.export_config(Path(body.dir), include_templates=body.include_templates,
                                     strip_secrets=body.strip_secrets)
    return {"files": [str(f) for f in files]}


@router.post("/config/import")
def config_import(body: ConfigImportBody, ctx: ApiContext = Depends(get_ctx)) -> dict:
    plan = configcode.import_config(Path(body.dir), dry_run=body.dry_run,
                                    include_templates=body.include_templates)
    if not body.dry_run:
        ctx.service.request_reload()
        ctx.publish("config", {"keys": ["*"]})
    return {
        "changes": [f"{change.kind}: {change.path}" for change in plan.changes],
        "warnings": list(plan.warnings),
        "backup_dir": str(plan.backup_dir) if plan.backup_dir is not None else None,
    }
