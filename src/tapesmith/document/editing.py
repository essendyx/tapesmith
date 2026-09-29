"""Editierlogik des WYSIWYG-Editors: reine, seiteneffektfreie Funktionen auf `LabelDocument`.

Kein Qt, kein Rendern, nur Geometrie auf dem Modell. Alle Funktionen geben ein neues Dokument
zurück; das Eingabedokument bleibt unverändert. Unbekannte IDs führen (über `find_object`) zu
`DocumentError`.
"""

import dataclasses
from collections.abc import Sequence

from tapesmith.document.model import (
    KIND_NAMES,
    Code128Object,
    DataMatrixObject,
    IconObject,
    ImageObject,
    LabelDocument,
    LabelObject,
    LineObject,
    QrObject,
    RectObject,
    TextObject,
    bbox,
    extent,
    find_object,
    new_id,
    replace_object,
    with_objects,
)
from tapesmith.i18n import N_, _t

NUDGE_SMALL = 1
NUDGE_LARGE = 8  # 1 mm bei 8 Punkten/mm (Umschalt+Pfeil)
DUPLICATE_OFFSET = (8, 8)
PRESETS = ("text", "qr", "code128", "datamatrix", "icon", "line", "arrow", "rect", "warnbar", "image")

_ALIGN_MODES = ("left", "hcenter", "right", "top", "vcenter", "bottom")
_ALIGN_HORIZONTAL = ("left", "hcenter", "right")
_DISTRIBUTE_AXES = ("h", "v")
_REORDER_OPS = ("raise", "lower", "top", "bottom")

_VERBS = {
    "add": N_("hinzugefügt"),
    "remove": N_("gelöscht"),
    "move": N_("verschoben"),
    "resize": N_("Größe geändert"),
    "edit": N_("geändert"),
    "align": N_("ausgerichtet"),
    "distribute": N_("verteilt"),
    "reorder": N_("Ebene geändert"),
    "duplicate": N_("dupliziert"),
    "rotate": N_("gedreht"),
    "flip": "gespiegelt",
}


def default_object(preset: str, doc: LabelDocument, content_dots: int, *, at: tuple[int, int] | None = None,
                    png: str | None = None) -> LabelObject:
    if preset not in PRESETS:
        raise ValueError(_t("Unbekannte Vorlage '{preset}' (erlaubt: {items})", preset=preset, items=', '.join(PRESETS)))
    x = at[0] if at is not None else extent(doc) + 8

    def y_of(h: int) -> int:
        return at[1] if at is not None else (content_dots - h) // 2

    if preset == "text":
        h = min(48, content_dots)
        return TextObject(id=new_id(doc, "text"), x=x, y=y_of(h), w=160, h=h, text=_t("Text"))
    if preset == "qr":
        h = min(88, content_dots)
        return QrObject(id=new_id(doc, "qr"), x=x, y=y_of(h), w=h, h=h, data="https://example.org")
    if preset == "code128":
        h = content_dots
        return Code128Object(id=new_id(doc, "code128"), x=x, y=y_of(h), w=240, h=h, data="12345678")
    if preset == "datamatrix":
        h = 64
        return DataMatrixObject(id=new_id(doc, "datamatrix"), x=x, y=y_of(h), w=64, h=h, data="P12")
    if preset == "icon":
        h = 48
        return IconObject(id=new_id(doc, "icon"), x=x, y=y_of(h), w=48, h=h, icon="tabler:star")
    if preset == "line":
        h = 8
        return LineObject(id=new_id(doc, "line"), x=x, y=y_of(h), w=120, h=h, direction="h")
    if preset == "arrow":
        h = 16
        return LineObject(id=new_id(doc, "line"), x=x, y=y_of(h), w=120, h=h, direction="h",
                          arrow_end=True, thickness=3)
    if preset == "rect":
        h = content_dots
        return RectObject(id=new_id(doc, "rect"), x=x, y=y_of(h), w=160, h=h, thickness=2)
    if preset == "warnbar":
        h = content_dots
        return RectObject(id=new_id(doc, "rect"), x=x, y=y_of(h), w=240, h=h, fill="stripes", thickness=0)
    # preset == "image"
    if not png:
        raise ValueError(_t("Bild-Vorlage braucht Bilddaten (png)"))
    h = content_dots
    return ImageObject(id=new_id(doc, "image"), x=x, y=y_of(h), w=88, h=h, png=png)


def add_object(doc: LabelDocument, obj: LabelObject) -> LabelDocument:
    return with_objects(doc, [*doc.objects, obj])


def remove_objects(doc: LabelDocument, ids: Sequence[str]) -> LabelDocument:
    for object_id in ids:
        find_object(doc, object_id)
    idset = set(ids)
    return with_objects(doc, [o for o in doc.objects if o.id not in idset])


def move_objects(doc: LabelDocument, ids: Sequence[str], dx: int, dy: int) -> LabelDocument:
    changes = {}
    for object_id in ids:
        obj = find_object(doc, object_id)
        if obj.locked:
            continue
        changes[object_id] = dataclasses.replace(obj, x=obj.x + dx, y=obj.y + dy)
    return with_objects(doc, [changes.get(o.id, o) for o in doc.objects])


def set_box(doc: LabelDocument, object_id: str, x: int, y: int, w: int, h: int) -> LabelDocument:
    obj = find_object(doc, object_id)
    new_obj = dataclasses.replace(obj, x=x, y=y, w=max(1, w), h=max(1, h))
    return replace_object(doc, new_obj)


def update_object(doc: LabelDocument, object_id: str, **changes) -> LabelDocument:
    obj = find_object(doc, object_id)
    new_obj = dataclasses.replace(obj, **changes)
    return replace_object(doc, new_obj)


def align(doc: LabelDocument, ids: Sequence[str], mode: str, *, reference: str = "selection",
          content_dots: int, length_dots: int | None = None) -> LabelDocument:
    if mode not in _ALIGN_MODES:
        raise ValueError(_t("Unbekannter Modus '{mode}' (erlaubt: {items})", mode=mode, items=', '.join(_ALIGN_MODES)))
    if reference not in ("selection", "label"):
        raise ValueError(_t("Unbekannte Referenz '{reference}' (erlaubt: selection, label)", reference=reference))
    horizontal = mode in _ALIGN_HORIZONTAL
    if reference == "label" and horizontal and length_dots is None:
        raise ValueError(_t("align: reference 'label' braucht length_dots für eine waagerechte Ausrichtung"))
    if reference == "selection":
        box = selection_box(doc, ids)
        if box is None:
            return doc
        bx0, by0, bx1, by1 = box
    else:
        bx0, by0, bx1, by1 = 0, 0, length_dots, content_dots

    changes = {}
    for object_id in ids:
        obj = find_object(doc, object_id)
        if mode == "left":
            changes[object_id] = dataclasses.replace(obj, x=bx0)
        elif mode == "right":
            changes[object_id] = dataclasses.replace(obj, x=bx1 - obj.w)
        elif mode == "hcenter":
            changes[object_id] = dataclasses.replace(obj, x=(bx0 + bx1 - obj.w) // 2)
        elif mode == "top":
            changes[object_id] = dataclasses.replace(obj, y=by0)
        elif mode == "bottom":
            changes[object_id] = dataclasses.replace(obj, y=by1 - obj.h)
        else:  # vcenter
            changes[object_id] = dataclasses.replace(obj, y=(by0 + by1 - obj.h) // 2)
    return with_objects(doc, [changes.get(o.id, o) for o in doc.objects])


def distribute(doc: LabelDocument, ids: Sequence[str], axis: str) -> LabelDocument:
    if axis not in _DISTRIBUTE_AXES:
        raise ValueError(_t("Unbekannte Achse '{axis}' (erlaubt: h, v)", axis=axis))
    if len(ids) < 3:
        return doc
    objs = [find_object(doc, object_id) for object_id in ids]
    if axis == "h":
        ordered = sorted(objs, key=lambda o: o.x)
        first, last = ordered[0], ordered[-1]
        span = (last.x + last.w) - first.x
        total_size = sum(o.w for o in ordered)
        gap = (span - total_size) // (len(ordered) - 1)
        changes = {}
        cur = first.x + first.w
        for obj in ordered[1:-1]:
            nx = cur + gap
            changes[obj.id] = dataclasses.replace(obj, x=nx)
            cur = nx + obj.w
    else:
        ordered = sorted(objs, key=lambda o: o.y)
        first, last = ordered[0], ordered[-1]
        span = (last.y + last.h) - first.y
        total_size = sum(o.h for o in ordered)
        gap = (span - total_size) // (len(ordered) - 1)
        changes = {}
        cur = first.y + first.h
        for obj in ordered[1:-1]:
            ny = cur + gap
            changes[obj.id] = dataclasses.replace(obj, y=ny)
            cur = ny + obj.h
    return with_objects(doc, [changes.get(o.id, o) for o in doc.objects])


def reorder(doc: LabelDocument, ids: Sequence[str], op: str) -> LabelDocument:
    if op not in _REORDER_OPS:
        raise ValueError(_t("Unbekannte Operation '{op}' (erlaubt: {items})", op=op, items=', '.join(_REORDER_OPS)))
    for object_id in ids:
        find_object(doc, object_id)
    sel = set(ids)
    objects = list(doc.objects)
    n = len(objects)
    if op == "top":
        others = [o for o in objects if o.id not in sel]
        selected = [o for o in objects if o.id in sel]
        return with_objects(doc, others + selected)
    if op == "bottom":
        others = [o for o in objects if o.id not in sel]
        selected = [o for o in objects if o.id in sel]
        return with_objects(doc, selected + others)
    idxs = [i for i, o in enumerate(objects) if o.id in sel]
    if op == "raise":
        for i in sorted(idxs, reverse=True):
            if i + 1 < n and objects[i + 1].id not in sel:
                objects[i], objects[i + 1] = objects[i + 1], objects[i]
    else:  # lower
        for i in sorted(idxs):
            if i - 1 >= 0 and objects[i - 1].id not in sel:
                objects[i], objects[i - 1] = objects[i - 1], objects[i]
    return with_objects(doc, objects)


def duplicate(doc: LabelDocument, ids: Sequence[str]) -> tuple[LabelDocument, tuple[str, ...]]:
    new_ids = []
    cur_doc = doc
    for object_id in ids:
        obj = find_object(doc, object_id)
        nid = new_id(cur_doc, obj.kind)
        dup = dataclasses.replace(obj, id=nid, x=obj.x + DUPLICATE_OFFSET[0], y=obj.y + DUPLICATE_OFFSET[1])
        cur_doc = with_objects(cur_doc, [*cur_doc.objects, dup])
        new_ids.append(nid)
    return cur_doc, tuple(new_ids)


def rotate_objects(doc: LabelDocument, ids: Sequence[str], degrees: int) -> LabelDocument:
    if degrees not in (90, -90, 180, -180):
        raise ValueError(_t("Unbekannter Drehwinkel {degrees} (erlaubt: ±90, ±180)", degrees=degrees))
    changes = {}
    for object_id in ids:
        obj = find_object(doc, object_id)
        new_rotation = (obj.rotation + degrees) % 360
        if degrees in (90, -90):
            cx = obj.x + obj.w // 2
            cy = obj.y + obj.h // 2
            new_w, new_h = obj.h, obj.w
            new_x = cx - new_w // 2
            new_y = cy - new_h // 2
            changes[object_id] = dataclasses.replace(obj, rotation=new_rotation, x=new_x, y=new_y,
                                                     w=new_w, h=new_h)
        else:
            changes[object_id] = dataclasses.replace(obj, rotation=new_rotation)
    return with_objects(doc, [changes.get(o.id, o) for o in doc.objects])


def flip_objects(doc: LabelDocument, ids: Sequence[str]) -> LabelDocument:
    changes = {}
    for object_id in ids:
        obj = find_object(doc, object_id)
        changes[object_id] = dataclasses.replace(obj, mirror=not obj.mirror)
    return with_objects(doc, [changes.get(o.id, o) for o in doc.objects])


def set_label_transform(doc: LabelDocument, *, mirror: bool | None = None,
                        rotate180: bool | None = None) -> LabelDocument:
    changes = {}
    if mirror is not None:
        changes["mirror"] = mirror
    if rotate180 is not None:
        changes["rotate180"] = rotate180
    if not changes:
        return doc
    return dataclasses.replace(doc, **changes)


def set_length(doc: LabelDocument, mode: str, length_mm: float | None = None) -> LabelDocument:
    if mode == "auto":
        length_mm = None
    return dataclasses.replace(doc, length_mode=mode, length_mm=length_mm)


def hit_test(doc: LabelDocument, x: int, y: int) -> str | None:
    for obj in reversed(doc.objects):
        if not obj.visible:
            continue
        x0, y0, x1, y1 = bbox(obj)
        if x0 <= x < x1 and y0 <= y < y1:
            return obj.id
    return None


def objects_in_rect(doc: LabelDocument, rect: tuple[int, int, int, int], *,
                     touch: bool = False) -> tuple[str, ...]:
    rx0, ry0, rx1, ry1 = rect
    result = []
    for obj in doc.objects:
        if not obj.visible:
            continue
        x0, y0, x1, y1 = bbox(obj)
        if touch:
            hit = x0 < rx1 and x1 > rx0 and y0 < ry1 and y1 > ry0
        else:
            hit = x0 >= rx0 and y0 >= ry0 and x1 <= rx1 and y1 <= ry1
        if hit:
            result.append(obj.id)
    return tuple(result)


def selection_box(doc: LabelDocument, ids: Sequence[str]) -> tuple[int, int, int, int] | None:
    if not ids:
        return None
    boxes = [bbox(find_object(doc, object_id)) for object_id in ids]
    x0 = min(b[0] for b in boxes)
    y0 = min(b[1] for b in boxes)
    x1 = max(b[2] for b in boxes)
    y1 = max(b[3] for b in boxes)
    return (x0, y0, x1, y1)


def step_label(action: str, doc: LabelDocument, ids: Sequence[str]) -> str:
    if action == "label":
        return _t("Label geändert")
    if action not in _VERBS:
        raise ValueError(_t("Unbekannte Aktion '{action}'", action=action))
    verb = _t(_VERBS[action])
    if len(ids) == 1:
        kind = find_object(doc, ids[0]).kind
        return f"{_t(KIND_NAMES[kind])} {verb}"
    return _t("{count} Objekte {verb}", count=len(ids), verb=verb)
