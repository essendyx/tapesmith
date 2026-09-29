"""Routen /api/v1 (Bereich editor).

Alle Bearbeitungen laufen über die vorhandenen Kernfunktionen aus `document.editing` und
`document.snap`; diese Datei übersetzt nur zwischen JSON und den reinen
Python-Funktionen (Guide-Umwandlung, `length_dots`-Berechnung).
"""

from __future__ import annotations

import base64
import binascii
import io

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict

from tapesmith.config import gui_setting
from tapesmith.document.editing import (
    add_object,
    align,
    default_object,
    distribute,
    duplicate,
    flip_objects,
    move_objects,
    remove_objects,
    reorder,
    rotate_objects,
    set_box,
    set_label_transform,
    set_length,
    step_label,
    update_object,
)
from tapesmith.document.from_spec import spec_to_document
from tapesmith.document.model import (
    DocumentError,
    LabelDocument,
    document_from_dict,
    document_to_dict,
    extent,
    prepare_embedded_image,
)
from tapesmith.document.snap import Guide, snap_move, snap_resize
from tapesmith.document.targets import load_targets
from tapesmith.jobs import spec_from_dict
from tapesmith.render.compose import mm_to_rows
from tapesmith.render.icons import IconMissing, categories, category_label, import_user_icon, render_icon, search_icons
from tapesmith.templates.fill import build_document, build_spec, resolve_values
from tapesmith.templates.gallery import sample_values
from tapesmith.templates.store import find_template
from tapesmith.webapi import documents as docstore
from tapesmith.webapi.context import ApiContext, get_ctx
from tapesmith.webapi.errors import NotFound
from tapesmith.i18n import _t

router = APIRouter()

MAX_IMAGE_BYTES = 10 * 1024 * 1024


# --------------------------------------------------------------------- Hilfsfunktionen

def _guide_json(guide: Guide) -> dict:
    return {"axis": "x" if guide.orientation == "v" else "y", "pos": guide.pos, "label": guide.kind}


def _edit_result(doc: LabelDocument, selected, step: str, guides) -> dict:
    return {"document": document_to_dict(doc), "selected": list(selected), "step_label": step,
            "guides": [_guide_json(g) for g in guides]}


def _length_dots(doc: LabelDocument, profile) -> int:
    """Länge des gerenderten Labels in Punkten (für Ausrichten am Label/Einrasten)."""
    if doc.length_mode in ("fixed", "max"):
        return mm_to_rows(doc.length_mm, profile)
    return extent(doc) + mm_to_rows(doc.margin_mm, profile)


def _decode_b64(data: str) -> bytes:
    try:
        return base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise DocumentError(_t("Bilddaten nicht lesbar (ungültiges Base64)")) from exc


def _icon_json(icon) -> dict:
    return {"ref": icon.ref, "name": icon.label, "category": icon.category,
            "category_label": category_label(icon.category), "source": icon.set}


# --------------------------------------------------------------------- /editor/new-object

class NewObjectBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    document: dict
    preset: str
    at: list[int] | None = None
    png: str | None = None


@router.post("/editor/new-object")
def editor_new_object(body: NewObjectBody, ctx: ApiContext = Depends(get_ctx)) -> dict:
    doc = document_from_dict(body.document)
    profile = ctx.profile()
    at = tuple(body.at) if body.at else None
    obj = default_object(body.preset, doc, profile.content_dots, at=at, png=body.png)
    new_doc = add_object(doc, obj)
    selected = [obj.id]
    step = step_label("add", new_doc, selected)
    return _edit_result(new_doc, selected, step, ())


# --------------------------------------------------------------------- /editor/op

class EditOpBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    document: dict
    op: str
    ids: list[str] = []
    params: dict = {}


@router.post("/editor/op")
def editor_op(body: EditOpBody, ctx: ApiContext = Depends(get_ctx)) -> dict:
    doc = document_from_dict(body.document)
    ids = list(body.ids)
    params = dict(body.params or {})
    profile = ctx.profile()
    content_dots = profile.content_dots
    action = body.op
    guides: tuple = ()

    if action == "move":
        dx = int(params.get("dx", 0))
        dy = int(params.get("dy", 0))
        if params.get("snap"):
            cfg = ctx.config()
            result = snap_move(doc, ids, dx, dy, content_dots=content_dots,
                               length_dots=_length_dots(doc, profile),
                               grid=int(gui_setting(cfg, "editor_grid_dots")),
                               enabled=bool(gui_setting(cfg, "editor_snap")))
            dx, dy, guides = result.dx, result.dy, result.guides
        new_doc = move_objects(doc, ids, dx, dy)
        step = step_label("move", new_doc, ids)
        selected = ids
    elif action == "set_box":
        if len(ids) != 1:
            raise ValueError(_t("set_box: braucht genau ein Objekt"))
        new_doc = set_box(doc, ids[0], int(params["x"]), int(params["y"]), int(params["w"]),
                          int(params["h"]))
        step = step_label("resize", new_doc, ids)
        selected = ids
    elif action == "update":
        if len(ids) != 1:
            raise ValueError(_t("update: braucht genau ein Objekt"))
        changes = dict(params.get("changes", {}))
        try:
            new_doc = update_object(doc, ids[0], **changes)
        except TypeError as exc:
            raise DocumentError(str(exc)) from exc
        step = step_label("edit", new_doc, ids)
        selected = ids
    elif action == "remove":
        step = step_label("remove", doc, ids)
        new_doc = remove_objects(doc, ids)
        selected = []
    elif action == "duplicate":
        new_doc, new_ids = duplicate(doc, ids)
        step = step_label("duplicate", doc, ids)
        selected = list(new_ids)
    elif action == "align":
        mode = params["mode"]
        reference = params.get("reference", "selection")
        new_doc = align(doc, ids, mode, reference=reference, content_dots=content_dots,
                        length_dots=_length_dots(doc, profile))
        step = step_label("align", new_doc, ids)
        selected = ids
    elif action == "distribute":
        axis = params["axis"]
        if len(ids) < 3:
            raise ValueError(_t("distribute: braucht mindestens drei Objekte"))
        new_doc = distribute(doc, ids, axis)
        step = step_label("distribute", new_doc, ids)
        selected = ids
    elif action == "reorder":
        new_doc = reorder(doc, ids, params["op"])
        step = step_label("reorder", new_doc, ids)
        selected = ids
    elif action == "rotate":
        new_doc = rotate_objects(doc, ids, int(params["degrees"]))
        step = step_label("rotate", new_doc, ids)
        selected = ids
    elif action == "flip":
        new_doc = flip_objects(doc, ids)
        step = step_label("flip", new_doc, ids)
        selected = ids
    elif action == "label_transform":
        new_doc = set_label_transform(doc, mirror=params.get("mirror"), rotate180=params.get("rotate180"))
        step = step_label("label", new_doc, ids)
        selected = ids
    elif action == "set_length":
        new_doc = set_length(doc, params["mode"], params.get("length_mm"))
        step = step_label("label", new_doc, ids)
        selected = ids
    else:
        raise ValueError(_t("Unbekannte Operation '{action}'", action=action))

    return _edit_result(new_doc, selected, step, guides)


# --------------------------------------------------------------------- /editor/snap

class SnapBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    document: dict
    ids: list[str]
    dx: int
    dy: int
    mode: str
    handle: str | None = None
    grid: int | None = None


@router.post("/editor/snap")
def editor_snap(body: SnapBody, ctx: ApiContext = Depends(get_ctx)) -> dict:
    doc = document_from_dict(body.document)
    profile = ctx.profile()
    grid = body.grid if body.grid is not None else int(gui_setting(ctx.config(), "editor_grid_dots"))
    length_dots = _length_dots(doc, profile)
    if body.mode == "move":
        result = snap_move(doc, body.ids, body.dx, body.dy, content_dots=profile.content_dots,
                           length_dots=length_dots, grid=grid)
    elif body.mode == "resize":
        if not body.handle:
            raise ValueError(_t("snap: Modus 'resize' braucht 'handle'"))
        result = snap_resize(doc, body.ids[0], body.handle, body.dx, body.dy,
                             content_dots=profile.content_dots, length_dots=length_dots, grid=grid)
    else:
        raise ValueError(_t("Unbekannter Modus '{mode}' (erlaubt: move, resize)", mode=body.mode))
    return {"dx": result.dx, "dy": result.dy, "guides": [_guide_json(g) for g in result.guides]}


# --------------------------------------------------------------------- /editor/image

class ImageBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    data_b64: str
    name: str | None = None


@router.post("/editor/image")
def editor_image(body: ImageBody) -> dict:
    raw = _decode_b64(body.data_b64)
    if len(raw) > MAX_IMAGE_BYTES:
        raise DocumentError(_t("Bild zu groß (höchstens {value} MB)", value=MAX_IMAGE_BYTES // (1024 * 1024)))
    try:
        with Image.open(io.BytesIO(raw)) as img:
            img.load()
            png_data = prepare_embedded_image(img)
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise DocumentError(_t("Bild nicht lesbar")) from exc
    with Image.open(io.BytesIO(base64.b64decode(png_data))) as prepared:
        width, height = prepared.size
    return {"png": png_data, "width": width, "height": height}


# --------------------------------------------------------------------- Dokumente (feste Pfade zuerst)

class FromTemplateBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    template: str
    values: dict[str, str] | None = None


@router.post("/documents/from-template")
def documents_from_template(body: FromTemplateBody, ctx: ApiContext = Depends(get_ctx)) -> dict:
    template = find_template(body.template)
    if template.kind == "generator":
        raise DocumentError(_t("Generator-Vorlagen lassen sich nicht im Editor bearbeiten"))
    inputs = body.values if body.values is not None else sample_values(template)
    resolved = resolve_values(template, inputs, ctx.now(), ctx.counters())
    if template.kind == "document":
        doc = build_document(template, resolved.values)
    else:
        spec = build_spec(template, resolved.values)
        doc = spec_to_document(spec, ctx.profile())
    return {"document": document_to_dict(doc)}


@router.get("/documents")
def documents_list() -> dict:
    return {"documents": [info.to_dict() for info in docstore.list_documents()]}


class DocumentBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    document: dict


@router.get("/documents/{name}")
def documents_get(name: str) -> dict:
    doc = docstore.load_document(name)
    return {"name": name, "document": document_to_dict(doc)}


@router.put("/documents/{name}")
def documents_put(name: str, body: DocumentBody) -> dict:
    doc = document_from_dict(body.document)
    info = docstore.save_document(name, doc)
    return info.to_dict()


@router.delete("/documents/{name}")
def documents_delete(name: str) -> dict:
    docstore.delete_document(name)
    return {}


@router.post("/documents/from-history/{entry_id}")
def documents_from_history(entry_id: int, ctx: ApiContext = Depends(get_ctx)) -> dict:
    try:
        entry = ctx.history().get(entry_id)
    except KeyError as exc:
        raise NotFound(str(exc)) from exc
    unusable = DocumentError(_t("Dieser Eintrag lässt sich nicht im Editor öffnen"))
    if entry.sensitive:
        raise unusable
    if entry.kind == "text" and entry.spec is not None:
        doc = spec_to_document(spec_from_dict(entry.spec), ctx.profile())
    elif entry.kind == "template" and entry.template:
        template = find_template(entry.template)
        if template.kind != "document":
            raise unusable
        doc = build_document(template, entry.values)
    else:
        raise unusable
    return {"document": document_to_dict(doc)}


# --------------------------------------------------------------------- Icons (feste Pfade zuerst)

@router.get("/icons/categories")
def icons_categories() -> dict:
    names = categories()
    return {"categories": names, "labels": {name: category_label(name) for name in names}}


@router.get("/icons/png")
def icons_png(ref: str, size: int = 48):
    if not 16 <= size <= 256:
        raise ValueError(_t("Icon-Größe muss zwischen 16 und 256 Punkten liegen"))
    try:
        image = render_icon(ref, size)
    except IconMissing as exc:
        raise NotFound(str(exc)) from exc
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png")


class UserIconBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str
    data_b64: str


@router.post("/icons/user")
def icons_user(body: UserIconBody) -> dict:
    raw = _decode_b64(body.data_b64)
    try:
        with Image.open(io.BytesIO(raw)) as img:
            img.load()
            ref = import_user_icon(img, body.name)
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise DocumentError(_t("Bild nicht lesbar")) from exc
    return {"ref": ref}


@router.get("/icons")
def icons_search(query: str = "", category: str | None = None, limit: int = 200) -> dict:
    icons = search_icons(query, category, limit)
    return {"icons": [_icon_json(i) for i in icons]}


# --------------------------------------------------------------------- /targets

@router.get("/targets")
def targets_list() -> dict:
    result = []
    for t in load_targets():
        length = t.max_length_mm if t.max_length_mm is not None else t.fixed_length_mm
        result.append({"id": t.id, "name": t.name, "max_length_mm": length, "note": t.note})
    return {"targets": result}
