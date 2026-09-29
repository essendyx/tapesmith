"""Kontextmenü- und URI-Aktionen in eine Route der Oberfläche auflösen.

Ablage `pending`: `ctx.extras[PENDING_KEY]` ist ein `dict` in Einfügereihenfolge (Schlüssel
`uuid4().hex[:12]`), höchstens `PENDING_MAX` Einträge, der älteste fliegt zuerst raus. Die Vorlagen-Routen
und die Oberfläche lesen dieselbe Ablage in derselben Form (`PendingJson`), deshalb keine
Abweichung von der hier angelegten Form.
"""

from __future__ import annotations

import base64
import json
import urllib.parse
from pathlib import Path
from uuid import uuid4

from tapesmith import integration
from tapesmith.dataimport.table import load_table
from tapesmith.templates.model import template_from_dict, template_to_dict
from tapesmith.webapi.context import ApiContext
from tapesmith.webapi.errors import NotFound
from tapesmith.i18n import _t

PENDING_KEY = "pending"
PENDING_MAX = 20
MAX_IMAGE_BYTES = 10 * 1024 * 1024


def _store(ctx: ApiContext) -> dict:
    return ctx.extras.setdefault(PENDING_KEY, {})


def put_pending(ctx: ApiContext, entry: dict) -> str:
    """Legt `entry` in der Ablage ab und gibt die neue Kennung zurück; verdrängt bei
    Überlauf den ältesten Eintrag (Einfügereihenfolge)."""
    store = _store(ctx)
    key = uuid4().hex[:12]
    store[key] = entry
    while len(store) > PENDING_MAX:
        oldest = next(iter(store))
        del store[oldest]
    return key


def get_pending(ctx: ApiContext, pending_id: str) -> dict:
    store = _store(ctx)
    if pending_id not in store:
        raise NotFound(_t("Ablage '{pending_id}' nicht gefunden", pending_id=pending_id))
    return store[pending_id]


def _lines_route(ctx: ApiContext, lines: tuple[str, ...]) -> str:
    if len(lines) <= 3:
        return "/schnelldruck?" + urllib.parse.urlencode({"text": "\n".join(lines)})
    pending_id = put_pending(ctx, {"type": "lines", "lines": list(lines)})
    return f"/vorlagen?import={pending_id}"


def resolve_action(ctx: ApiContext, *, uri: str | None = None, open: str | None = None,
                   path: str | None = None) -> dict:
    """Löst eine URI (`tapesmith://…`) oder eine Kontextmenü-Aktion (`open` + `path`) in eine
    Route der Oberfläche auf (`ActionJson`: `kind`, `route`, `note`)."""
    if uri is not None:
        action = integration.parse_uri(uri)
    elif open is not None:
        if not path:
            raise ValueError(_t("Parameter 'path' fehlt"))
        action = integration.file_action(open, Path(path))
    else:
        raise ValueError(_t("Bitte 'uri' oder 'open' angeben"))

    kind = action.kind
    note = action.note

    if kind == "template" and action.template is not None:
        route = "/vorlagen?" + urllib.parse.urlencode(
            {"vorlage": action.template, "werte": json.dumps(action.values, ensure_ascii=False)})
    elif kind == "template":
        file_path = action.path
        assert file_path is not None
        data = json.loads(file_path.read_text(encoding="utf-8"))
        template = template_from_dict(data, path=file_path)
        definition = template_to_dict(template)
        pending_id = put_pending(
            ctx, {"type": "template_file", "name": file_path.name, "definition": definition})
        route = f"/vorlagen?datei={pending_id}"
    elif kind in ("text", "lines"):
        route = _lines_route(ctx, action.lines)
    elif kind == "qr":
        route = "/qr?" + urllib.parse.urlencode(
            {"inhalt": action.qr or "", "zeilen": json.dumps(list(action.lines), ensure_ascii=False)})
    elif kind == "batch":
        file_path = action.path
        assert file_path is not None
        table = load_table(file_path)
        pending_id = put_pending(ctx, {
            "type": "table", "headers": list(table.headers),
            "rows": [list(row) for row in table.rows], "source_name": file_path.name,
        })
        route = f"/vorlagen?import={pending_id}"
    elif kind == "image":
        file_path = action.path
        assert file_path is not None
        data = file_path.read_bytes()
        if len(data) > MAX_IMAGE_BYTES:
            raise ValueError(_t("Bild zu groß (max. {max_image_bytes} Bytes)", max_image_bytes=MAX_IMAGE_BYTES))
        pending_id = put_pending(ctx, {
            "type": "image", "name": file_path.name,
            "data_b64": base64.b64encode(data).decode("ascii"),
        })
        route = f"/editor?import={pending_id}"
    else:
        raise ValueError(_t("Unbekannte Aktion '{kind}'", kind=kind))

    return {"kind": kind, "route": route, "note": note}
