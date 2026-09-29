"""Vorschau-Helfer der Web-API: WYSIWYG-Bilder aus dem Python-Kern als Base64-PNG."""

from __future__ import annotations

import base64
import io
from collections.abc import Sequence
from typing import TYPE_CHECKING

from PIL import Image

from tapesmith.gui.preview_model import build_preview
from tapesmith.jobs import JobMeta
from tapesmith.pipeline import PrintLabel
from tapesmith.webapi.printing import PrintOptionsModel, build_request

if TYPE_CHECKING:  # pragma: no cover
    from tapesmith.webapi.context import ApiContext


def png_b64(image: Image.Image) -> str:
    """PNG als Base64 ohne `data:`-Präfix."""
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _unique(items) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def preview_json(ctx: ApiContext, labels: Sequence[PrintLabel], meta: JobMeta, opts: PrintOptionsModel, *,
                 extra_warnings: Sequence[str] = ()) -> dict:
    """`PreviewJson`: geplant wie beim Druck (inklusive Rückfragen und Rollenprüfung)."""
    plan = ctx.service.pipeline.plan(build_request(labels, meta, opts))
    data = build_preview(plan.chain, ctx.profile(), ctx.tape())
    decision = plan.decision
    return {
        "design_png": png_b64(data.design),
        "raster_png": png_b64(data.raster.convert("1")),
        "width": data.design.width,
        "height": data.design.height,
        "info": data.info,
        "content_mm": data.content_mm,
        "tape_mm": data.tape_mm,
        "labels": data.labels,
        "jobs": data.jobs,
        "estimated": data.estimated,
        "balance_text": plan.balance_text,
        "decision": {"allowed": decision.allowed, "needs_confirmation": decision.needs_confirmation,
                     "reasons": list(decision.reasons)},
        "warnings": _unique([*plan.chain.warnings, *plan.check_warnings, *extra_warnings]),
    }


def empty_render(title: str = "", **fields) -> dict:
    """`RenderJson`-Grundgerüst: nicht druckbar, alle Listen leer, alles andere None."""
    data = {
        "ok": False, "title": title, "preview": None, "errors": [], "warnings": [], "issues": [],
        "fixes": [], "font_size": None, "qr": None, "values": None, "shortened": [], "notes": [],
        "tape_reason": None, "missing_secrets": [], "editor": None,
    }
    data.update(fields)
    return data
