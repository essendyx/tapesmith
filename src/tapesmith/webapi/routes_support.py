"""Route „Problem melden“: `POST /support/report` liefert den Support-Bericht als Zip.

Nur Rolle `admin` bzw. Sitzung (nicht in der Positivliste von `webapi/access.py`). Schlägt die
Statusabfrage fehl, entsteht der Bericht trotzdem (ohne Druckerstatus).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from fastapi.responses import Response

from tapesmith import config as config_mod
from tapesmith import support
from tapesmith.webapi.context import ApiContext, get_ctx
from tapesmith.webapi.convert import status_json

log = logging.getLogger(__name__)

router = APIRouter()


def _status(ctx: ApiContext, cfg: dict) -> dict | None:
    try:
        report = ctx.service.status(fresh=False)
        status = status_json(report, now=ctx.now(), mac=cfg.get("mac"))
        status["queue"] = ctx.service.queue_snapshot()
        return status
    except Exception as exc:  # noqa: BLE001 (Bericht auch ohne Status)
        log.warning("Support-Bericht ohne Druckerstatus: %s", exc)
        return None


@router.post("/support/report")
def support_report(ctx: ApiContext = Depends(get_ctx)) -> Response:
    try:
        cfg = ctx.config()
    except Exception as exc:  # noqa: BLE001 (kaputte Konfiguration gehört in den Bericht)
        cfg = dict(config_mod.DEFAULTS)
        cfg["konfiguration_fehler"] = str(exc)
    now = ctx.now()
    content = support.build_report(cfg, status=_status(ctx, cfg), now=now)
    filename = support.report_filename(now)
    return Response(content, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})
