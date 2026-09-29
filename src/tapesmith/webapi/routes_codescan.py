"""Route /api/v1/homelab/codescan: Seriennummer aus einem Foto des Herstelleraufklebers
lesen. `ValueError` (ungültiges Base64, zu groß, kein lesbares Bild) wird zentral über
`webapi.errors.install_handlers` als 422 beantwortet."""

from __future__ import annotations

import base64
import binascii

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from tapesmith.integrations.codescan import MAX_BYTES, scan
from tapesmith.templates.serial import shorten
from tapesmith.webapi.context import ApiContext, get_ctx
from tapesmith.i18n import _t

router = APIRouter()


class CodescanBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    image_b64: str
    name: str | None = None


def _decode_image(image_b64: str) -> bytes:
    text = image_b64.strip()
    if text.startswith("data:"):
        _, _, text = text.partition(",")
    try:
        raw = base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(_t("Bild: ungültiges Base64")) from exc
    if len(raw) > MAX_BYTES:
        raise ValueError(_t("Bild zu groß (max. {value} MB)", value=MAX_BYTES // (1024 * 1024)))
    return raw


@router.post("/homelab/codescan")
def post_codescan(body: CodescanBody, ctx: ApiContext = Depends(get_ctx)) -> dict:
    raw = _decode_image(body.image_b64)
    result = scan(raw)
    best = result.best.serial if result.best else None
    return {
        "width": result.width,
        "height": result.height,
        "hits": [
            {"text": hit.text, "format": hit.format, "position": list(hit.position) if hit.position else None}
            for hit in result.hits
        ],
        "candidates": [
            {"serial": c.serial, "score": c.score, "reason": c.reason, "text": c.hit.text, "format": c.hit.format}
            for c in result.candidates
        ],
        "best": best,
        "shortened": shorten(best) if best else None,
    }
