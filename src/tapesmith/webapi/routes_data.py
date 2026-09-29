"""Routen /api/v1 (Bereich data).

Verlauf, Warteschlange, Statistik, Inventar, Datenträger-Assistent und SSH-Disk-Scanner.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, StrictBool
from starlette.background import BackgroundTask

from tapesmith import config as config_mod
from tapesmith.archive import archive_entry, git_commit
from tapesmith.dataimport.batch import batch_meta, build_batch, commit_counters
from tapesmith.drives import list_drives
from tapesmith.export import export_heads, format_for
from tapesmith.integrations import scancache
from tapesmith.inventory import contents_lines, loan_lines, render_box_label, render_lines_label
from tapesmith.pipeline import labels_from_result
from tapesmith.sshscan import SshError, find_host, hosts_from_config, rows_for_template, scan_host
from tapesmith.stats import roll_usage, totals, usage_by
from tapesmith.tape.preview import colorize
from tapesmith.templates.store import find_template
from tapesmith.webapi import datajson as dj
from tapesmith.webapi.context import ApiContext, get_ctx
from tapesmith.webapi.errors import NotFound, error_json
from tapesmith.webapi.previews import empty_render, png_b64, preview_json
from tapesmith.webapi.printing import PrintOptionsModel, options_from_json, submit_labels
from tapesmith.i18n import N_, _t

log = logging.getLogger(__name__)

router = APIRouter()

EXPORT_MEDIA = {"png": "image/png", "pdf": "application/pdf", "pbm": "image/x-portable-bitmap"}
NO_HEAD_MESSAGE = N_("Für sensible Aufträge wird kein Bild gespeichert")


class EmptyBody(BaseModel):
    model_config = ConfigDict(extra="ignore")


class MoveBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    position: int


class AutoRetryBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    on: StrictBool


class BoxCreateBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    location: str = ""
    note: str = ""


class BoxUpdateBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    location: str | None = None
    note: str | None = None


class ItemCreateBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str
    box_id: str | None = None
    qty: int = 1
    note: str = ""


class ItemMoveBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    box_id: str | None = None


class LoanCreateBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    item: str
    person: str
    due: str | None = None
    note: str = ""


class InventoryLabelBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    type: str
    box_id: str | None = None
    loan_id: int | None = None
    options: dict | None = None


class SshScanBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    host: str


class SshSeriesBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    host: str
    disks: list[dict]
    slots: dict[str, str] = {}
    chain: bool = False
    cut_marks: bool = True
    options: dict | None = None


# ---------- Verlauf ----------

@router.get("/history")
def history_list(query: str = "", limit: int = 50, ctx: ApiContext = Depends(get_ctx)) -> dict:
    if not (1 <= limit <= 500):
        raise ValueError(_t("limit muss 1..500 sein, nicht {limit}", limit=limit))
    store = ctx.history()
    entries = store.search(query, limit)
    return {"entries": [dj.history_entry_json(e, store) for e in entries]}


@router.get("/history/{entry_id}")
def history_get(entry_id: int, ctx: ApiContext = Depends(get_ctx)) -> dict:
    store = ctx.history()
    try:
        entry = store.get(entry_id)
    except KeyError as exc:
        raise NotFound(str(exc)) from exc
    return dj.history_entry_json(entry, store)


@router.get("/history/{entry_id}/thumb.png")
def history_thumb(entry_id: int, ctx: ApiContext = Depends(get_ctx)):
    store = ctx.history()
    try:
        thumb = store.thumbnail(entry_id)
    except KeyError as exc:
        raise NotFound(str(exc)) from exc
    if thumb is None:
        raise NotFound(_t("Verlaufseintrag {entry_id} hat keine Miniatur", entry_id=entry_id))
    tmpdir = Path(tempfile.mkdtemp(prefix="p12-thumb-"))
    path = tmpdir / f"verlauf-{entry_id}-thumb.png"
    thumb.save(path, "PNG")
    return FileResponse(path, media_type="image/png", background=BackgroundTask(shutil.rmtree, tmpdir, True))


@router.get("/history/{entry_id}/export")
def history_export(entry_id: int, format: str, ctx: ApiContext = Depends(get_ctx)):
    store = ctx.history()
    try:
        store.get(entry_id)
        head = store.head_image(entry_id)
    except KeyError as exc:
        raise NotFound(str(exc)) from exc
    if head is None:
        raise NotFound(_t(NO_HEAD_MESSAGE))
    fmt = format_for(Path(f"x.{format}"), format)
    filename = f"verlauf-{entry_id}.{fmt}"
    tmpdir = Path(tempfile.mkdtemp(prefix="p12-export-"))
    path = tmpdir / filename
    export_heads(path, [head], ctx.profile(), fmt=fmt)
    return FileResponse(path, media_type=EXPORT_MEDIA[fmt], filename=filename,
                        background=BackgroundTask(shutil.rmtree, tmpdir, True))


@router.post("/history/{entry_id}/archive")
def history_archive(entry_id: int, _body: EmptyBody | None = None, ctx: ApiContext = Depends(get_ctx)) -> dict:
    cfg = ctx.config()
    directory = (cfg.get("archive") or {}).get("dir")
    if not directory:
        raise ValueError(_t("Archiv ist nicht eingerichtet (archive.dir)"))
    store = ctx.history()
    try:
        entry = store.get(entry_id)
        head = store.head_image(entry_id)
    except KeyError as exc:
        raise NotFound(str(exc)) from exc
    files = archive_entry(entry, head, Path(directory), ctx.profile())
    notes = [_t("Archiviert: {p}", p=p) for p in files]
    if bool((cfg.get("archive") or {}).get("git_commit", False)):
        message = f"Label #{entry.id}: {entry.title}"
        result = git_commit(files, Path(directory), message)
        notes.append(result if result is not None else "committet")
    return {"notes": notes}


# ---------- Warteschlange ----------

@router.get("/queue")
def queue_get(include_done: bool = False, ctx: ApiContext = Depends(get_ctx)) -> dict:
    return ctx.service.queue_snapshot(include_done)


@router.post("/queue/retry-all")
def queue_retry_all(_body: EmptyBody | None = None, ctx: ApiContext = Depends(get_ctx)) -> dict:
    ctx.service.queue_retry(None)
    return {}


@router.post("/queue/pause")
def queue_pause(_body: EmptyBody | None = None, ctx: ApiContext = Depends(get_ctx)) -> dict:
    ctx.service.queue_pause()
    return {}


@router.post("/queue/resume")
def queue_resume(_body: EmptyBody | None = None, ctx: ApiContext = Depends(get_ctx)) -> dict:
    ctx.service.queue_resume()
    return {}


@router.put("/queue/auto-retry")
def queue_auto_retry(body: AutoRetryBody, ctx: ApiContext = Depends(get_ctx)) -> dict:
    config_mod.set_setting("queue.auto_retry", body.on)
    ctx.service.request_reload()
    ctx.publish("config", {"keys": ["queue.auto_retry"]})
    return ctx.service.queue_snapshot()


@router.post("/queue/{job_id}/cancel")
def queue_cancel(job_id: int, _body: EmptyBody | None = None, ctx: ApiContext = Depends(get_ctx)) -> dict:
    return {"ok": bool(ctx.service.queue_cancel(job_id))}


@router.post("/queue/{job_id}/duplicate")
def queue_duplicate(job_id: int, _body: EmptyBody | None = None, ctx: ApiContext = Depends(get_ctx)) -> dict:
    try:
        new_id = ctx.service.queue_duplicate(job_id)
    except KeyError as exc:
        raise NotFound(str(exc)) from exc
    return {"id": new_id}


@router.post("/queue/{job_id}/retry")
def queue_retry_one(job_id: int, _body: EmptyBody | None = None, ctx: ApiContext = Depends(get_ctx)) -> dict:
    try:
        ctx.service.queue_retry(job_id)
    except KeyError as exc:
        raise NotFound(str(exc)) from exc
    return {}


@router.post("/queue/{job_id}/move")
def queue_move(job_id: int, body: MoveBody, ctx: ApiContext = Depends(get_ctx)) -> dict:
    try:
        ctx.service.queue_move(job_id, body.position)
    except KeyError as exc:
        raise NotFound(str(exc)) from exc
    return {}


# ---------- Statistik ----------

@router.get("/stats/rolls")
def stats_rolls(ctx: ApiContext = Depends(get_ctx)) -> dict:
    return {"rolls": [dj.roll_usage_json(r) for r in roll_usage(ctx.rolls())]}


@router.get("/stats")
def stats_get(by: str = "monat", since: str | None = None, ctx: ApiContext = Depends(get_ctx)) -> dict:
    since_dt = datetime.strptime(since, "%Y-%m-%d") if since else None
    rows = usage_by(ctx.history(), by, since=since_dt)
    return {"by": by, "rows": [dj.usage_row_json(r) for r in rows], "totals": dj.usage_row_json(totals(rows))}


# ---------- Inventar: Boxen ----------

@router.get("/inventory/boxes")
def inventory_boxes(ctx: ApiContext = Depends(get_ctx)) -> dict:
    inv = ctx.inventory()
    return {"boxes": [dj.box_json(b, len(inv.items(b.id))) for b in inv.boxes()]}


@router.post("/inventory/boxes")
def inventory_box_create(body: BoxCreateBody, ctx: ApiContext = Depends(get_ctx)) -> dict:
    box = ctx.inventory().add_box(body.id, body.location, note=body.note)
    return dj.box_json(box, 0)


@router.get("/inventory/boxes/{box_id}")
def inventory_box_get(box_id: str, ctx: ApiContext = Depends(get_ctx)) -> dict:
    inv = ctx.inventory()
    try:
        box = inv.box(box_id)
    except KeyError as exc:
        raise NotFound(str(exc)) from exc
    return dj.box_detail_json(box, inv.items(box_id))


@router.put("/inventory/boxes/{box_id}")
def inventory_box_update(box_id: str, body: BoxUpdateBody, ctx: ApiContext = Depends(get_ctx)) -> dict:
    inv = ctx.inventory()
    try:
        box = inv.update_box(box_id, location=body.location, note=body.note)
    except KeyError as exc:
        raise NotFound(str(exc)) from exc
    return dj.box_json(box, len(inv.items(box_id)))


@router.delete("/inventory/boxes/{box_id}")
def inventory_box_delete(box_id: str, ctx: ApiContext = Depends(get_ctx)) -> dict:
    try:
        ctx.inventory().remove_box(box_id)
    except KeyError as exc:
        raise NotFound(str(exc)) from exc
    return {}


# ---------- Inventar: Gegenstände ----------

@router.post("/inventory/items")
def inventory_item_create(body: ItemCreateBody, ctx: ApiContext = Depends(get_ctx)) -> dict:
    item = ctx.inventory().add_item(body.name, box_id=body.box_id, qty=body.qty, note=body.note)
    return dj.item_json(item)


@router.put("/inventory/items/{item_id}")
def inventory_item_move(item_id: int, body: ItemMoveBody, ctx: ApiContext = Depends(get_ctx)) -> dict:
    try:
        item = ctx.inventory().move_item(item_id, body.box_id)
    except KeyError as exc:
        raise NotFound(str(exc)) from exc
    return dj.item_json(item)


@router.delete("/inventory/items/{item_id}")
def inventory_item_delete(item_id: int, ctx: ApiContext = Depends(get_ctx)) -> dict:
    try:
        ctx.inventory().remove_item(item_id)
    except KeyError as exc:
        raise NotFound(str(exc)) from exc
    return {}


# ---------- Inventar: Suche, Verleih ----------

@router.get("/inventory/search")
def inventory_search(q: str = "", ctx: ApiContext = Depends(get_ctx)) -> dict:
    inv = ctx.inventory()
    hits = inv.search(q)
    return {"hits": [dj.search_hit_json(h, len(inv.items(h.box.id)) if h.box else None) for h in hits]}


@router.get("/inventory/loans")
def inventory_loans(open: bool = True, ctx: ApiContext = Depends(get_ctx)) -> dict:
    today = ctx.now().date()
    loans = ctx.inventory().loans(open_only=open)
    return {"loans": [dj.loan_json(loan, today) for loan in loans]}


@router.post("/inventory/loans")
def inventory_loan_create(body: LoanCreateBody, ctx: ApiContext = Depends(get_ctx)) -> dict:
    due = date.fromisoformat(body.due) if body.due else None
    loan = ctx.inventory().lend(body.item, body.person, due=due, note=body.note)
    return dj.loan_json(loan, ctx.now().date())


@router.post("/inventory/loans/{loan_id}/return")
def inventory_loan_return(loan_id: int, _body: EmptyBody | None = None, ctx: ApiContext = Depends(get_ctx)) -> dict:
    try:
        loan = ctx.inventory().give_back(loan_id, on=ctx.now().date())
    except KeyError as exc:
        raise NotFound(str(exc)) from exc
    return dj.loan_json(loan, ctx.now().date())


# ---------- Inventar: Labels ----------

def _inventory_label_source(body: InventoryLabelBody, ctx: ApiContext):
    """(labels, meta, on_done) für die drei Label-Arten der Inventarseite."""
    inv = ctx.inventory()
    profile = ctx.profile()
    tape = ctx.tape()
    if body.type == "box":
        if not body.box_id:
            raise ValueError(_t("box_id fehlt"))
        try:
            box = inv.box(body.box_id)
        except KeyError as exc:
            raise NotFound(str(exc)) from exc
        counters = ctx.counters()
        result, meta, counter_keys = render_box_label(box, profile, counters=counters, tape=tape,
                                                       now=ctx.now(), source="gui")

        def commit(_outcome) -> None:
            for key in counter_keys:
                counters.commit(key)

        return labels_from_result(result), meta, commit
    if body.type == "content":
        if not body.box_id:
            raise ValueError(_t("box_id fehlt"))
        try:
            box = inv.box(body.box_id)
        except KeyError as exc:
            raise NotFound(str(exc)) from exc
        lines = contents_lines(box, inv.items(box.id))
        result, meta = render_lines_label(lines, profile, tape=tape, title=_t("Inhalt {id}", id=box.id), source="gui")
        return labels_from_result(result), meta, None
    if body.type == "loan":
        if body.loan_id is None:
            raise ValueError(_t("loan_id fehlt"))
        try:
            loan = inv.loan(body.loan_id)
        except KeyError as exc:
            raise NotFound(str(exc)) from exc
        lines = loan_lines(loan)
        result, meta = render_lines_label(lines, profile, tape=tape, title=_t("Verleih {item}", item=loan.item), source="gui")
        return labels_from_result(result), meta, None
    raise ValueError(_t("Unbekannte Label-Art '{type}' (erlaubt: box, content, loan)", type=body.type))


@router.post("/inventory/labels/render")
def inventory_labels_render(body: InventoryLabelBody, ctx: ApiContext = Depends(get_ctx)) -> dict:
    labels, meta, _commit = _inventory_label_source(body, ctx)
    opts = PrintOptionsModel()
    preview = preview_json(ctx, labels, meta, opts)
    return empty_render(title=meta.title, ok=True, preview=preview, warnings=list(preview["warnings"]))


@router.post("/inventory/labels/print")
def inventory_labels_print(body: InventoryLabelBody, ctx: ApiContext = Depends(get_ctx)) -> dict:
    labels, meta, commit = _inventory_label_source(body, ctx)
    opts = options_from_json(body.options)
    return submit_labels(ctx, labels, meta, opts, on_done=commit)


# ---------- Datenträger ----------

@router.get("/drives")
def drives_get(ctx: ApiContext = Depends(get_ctx)) -> dict:
    return {"drives": [dj.drive_json(d) for d in list_drives(ctx.drives_backend)]}


# ---------- SSH ----------

@router.get("/ssh/hosts")
def ssh_hosts(ctx: ApiContext = Depends(get_ctx)) -> dict:
    return {"hosts": [dj.ssh_host_json(h) for h in hosts_from_config(ctx.config())]}


@router.post("/ssh/scan")
def ssh_scan(body: SshScanBody, ctx: ApiContext = Depends(get_ctx)):
    cfg = ctx.config()
    try:
        host = find_host(cfg, body.host)
    except ValueError as exc:
        raise NotFound(str(exc)) from exc
    try:
        disks = scan_host(host, runner=ctx.ssh_runner, timeout_s=config_mod.setting(cfg, "ssh.timeout_s"),
                          strict_host_key=config_mod.setting(cfg, "ssh.strict_host_key"))
    except SshError as exc:
        return JSONResponse(error_json("SSH", str(exc)), status_code=502)
    try:
        scancache.save_scan(host.name, disks, when=ctx.now())
    except (OSError, ValueError) as exc:
        log.warning("Scan-Cache für %s nicht gespeichert: %s", host.name, exc)
    return {"host": body.host, "disks": [dj.disk_json(d) for d in disks]}


def _series_plan(body: SshSeriesBody, ctx: ApiContext):
    disks = [dj.disk_row_from_json(d) for d in body.disks]
    rows = rows_for_template(disks, body.slots)
    template = find_template("datentraeger")
    return build_batch(template, rows, ctx.profile(), now=ctx.now(), counters=ctx.counters(), tape=ctx.tape())


def _series_previews(plan, ctx: ApiContext) -> list[dict]:
    previews = []
    for row in plan.rows:
        if row.render is None:
            continue
        landscape = row.render.result.landscape
        design = colorize(landscape, ctx.tape())
        title = " · ".join(v for v in row.inputs.values() if v) or _t("Zeile {value}", value=row.index + 1)
        previews.append({"index": row.index, "title": title, "design_png": png_b64(design)})
    return previews


@router.post("/ssh/series")
def ssh_series(body: SshSeriesBody, ctx: ApiContext = Depends(get_ctx)) -> dict:
    plan = _series_plan(body, ctx)
    return {
        "count": len(plan.labels),
        "summary": plan.summary(ctx.profile(), chain=body.chain, cut_marks=body.cut_marks),
        "mapping": {},
        "headers": [],
        "warnings": [],
        "errors": list(plan.errors),
        "previews": _series_previews(plan, ctx),
    }


@router.post("/ssh/series/print")
def ssh_series_print(body: SshSeriesBody, ctx: ApiContext = Depends(get_ctx)) -> dict:
    plan = _series_plan(body, ctx)
    if plan.errors:
        raise ValueError("; ".join(plan.errors))
    opts_data: dict[str, Any] = dict(body.options or {})
    opts_data["chain"] = body.chain
    opts_data["cut_marks"] = body.cut_marks
    opts = options_from_json(opts_data)
    meta = batch_meta(plan, "gui")
    counters = ctx.counters()

    def commit(_outcome) -> None:
        commit_counters(plan, counters)

    return submit_labels(ctx, plan.labels, meta, opts, on_done=commit)
