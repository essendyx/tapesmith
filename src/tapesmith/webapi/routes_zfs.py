"""Routen `/api/v1/homelab/zfs/*`: Assistent „Platte tauschen".

Fehlerabbildung wie die bestehende Route `/ssh/scan` in `routes_data.py`: unbekannter Host ->
`NotFound` (404), `SshError` -> 502 mit `error.kind == "SSH"`. Der Endpunkt führt nie `zpool` aus.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from tapesmith import config as config_mod
from tapesmith.integrations import zfsreplace
from tapesmith.sshscan import SshError, find_host
from tapesmith.webapi import datajson as dj
from tapesmith.webapi.context import ApiContext, get_ctx
from tapesmith.webapi.errors import NotFound, error_json
from tapesmith.i18n import _t

router = APIRouter()


class ZfsScanBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    host: str


class ZfsPlanBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    host: str
    old: str
    new_device: str
    slot: str
    reason: str = ""


def _pool_device_json(device: zfsreplace.PoolDevice) -> dict:
    return {
        "pool": device.pool, "vdev": device.vdev, "name": device.name, "state": device.state,
        "read": device.read, "write": device.write, "cksum": device.cksum, "note": device.note,
        "was_path": device.was_path, "by_id": device.by_id, "partition": device.partition,
        "device": device.device,
    }


def _pool_status_json(pool: zfsreplace.PoolStatus) -> dict:
    return {"name": pool.name, "state": pool.state, "errors": pool.errors,
            "devices": [_pool_device_json(d) for d in pool.devices]}


def _candidate_json(candidate: zfsreplace.Candidate) -> dict:
    return {"disk": dj.disk_json(candidate.disk), "reason": candidate.reason}


def _overview_json(ov: zfsreplace.ZfsOverview) -> dict:
    return {
        "host": ov.host, "scanned_at": ov.scanned_at, "previous_scanned_at": ov.previous_scanned_at,
        "disks": [dj.disk_json(d) for d in ov.disks],
        "pools": [_pool_status_json(p) for p in ov.pools],
        "problems": [_pool_device_json(d) for d in ov.problems],
        "candidates": [_candidate_json(c) for c in ov.candidates],
    }


def _plan_json(plan: zfsreplace.ReplacePlan) -> dict:
    return {
        "host": plan.host, "pool": plan.pool, "old": _pool_device_json(plan.old),
        "old_serial": plan.old_serial, "old_model": plan.old_model, "new": dj.disk_json(plan.new),
        "command": plan.command, "hints": list(plan.hints), "changelog_md": plan.changelog_md,
        "old_label": {"template": "platte-defekt", "values": plan.old_label},
        "new_label": {"template": "datentraeger", "values": plan.new_label},
    }


@router.post("/homelab/zfs/scan")
def zfs_scan(body: ZfsScanBody, ctx: ApiContext = Depends(get_ctx)):
    cfg = ctx.config()
    try:
        host = find_host(cfg, body.host)
    except (ValueError, KeyError) as exc:
        raise NotFound(str(exc)) from exc
    try:
        ov, stdout = zfsreplace.overview(
            host, runner=ctx.ssh_runner, timeout_s=config_mod.setting(cfg, "ssh.timeout_s"),
            strict_host_key=config_mod.setting(cfg, "ssh.strict_host_key"), now=ctx.now,
        )
    except SshError as exc:
        return JSONResponse(error_json("SSH", str(exc)), status_code=502)
    ctx.extras.setdefault("zfs_last", {})[body.host] = {"overview": ov, "stdout": stdout}
    return _overview_json(ov)


@router.post("/homelab/zfs/plan")
def zfs_plan(body: ZfsPlanBody, ctx: ApiContext = Depends(get_ctx)) -> dict:
    zfs_last = ctx.extras.get("zfs_last") or {}
    entry = zfs_last.get(body.host)
    if entry is None:
        raise ValueError(_t("Erst scannen"))
    ov = entry["overview"]
    plan = zfsreplace.build_plan(ov, body.old, body.new_device, slot=body.slot,
                                 today=ctx.now().date(), reason=body.reason)
    return _plan_json(plan)
