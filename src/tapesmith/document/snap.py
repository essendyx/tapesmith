"""Einrasten/Hilfslinien beim Verschieben und Größenändern: Bandmitte, Druckkanten, andere
Objekte und Punktraster. Reine Geometrie, kein Qt.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from tapesmith.document.editing import selection_box
from tapesmith.document.model import LabelDocument, bbox, find_object
from tapesmith.i18n import _t

SNAP_THRESHOLD = 4

_KIND_PRIORITY = {"center": 0, "edge": 1, "object": 2}

_HANDLE_EDGES = {
    "n": ("y0",), "s": ("y1",), "e": ("x1",), "w": ("x0",),
    "ne": ("y0", "x1"), "nw": ("y0", "x0"), "se": ("y1", "x1"), "sw": ("y1", "x0"),
}


@dataclass(frozen=True)
class Guide:
    orientation: str      # "v" (senkrechte Linie bei x = pos) | "h" (waagerechte Linie bei y = pos)
    pos: int
    kind: str              # "center" | "edge" | "object" | "grid"


@dataclass(frozen=True)
class SnapResult:
    dx: int
    dy: int
    guides: tuple[Guide, ...]


def _object_candidates(doc: LabelDocument, ids: Sequence[str], axis: str) -> list[tuple[int, str]]:
    sel = set(ids)
    out = []
    for obj in doc.objects:
        if obj.id in sel or not obj.visible:
            continue
        x0, y0, x1, y1 = bbox(obj)
        if axis == "x":
            out.append((x0, "object"))
            out.append(((x0 + x1) // 2, "object"))
            out.append((x1, "object"))
        else:
            out.append((y0, "object"))
            out.append(((y0 + y1) // 2, "object"))
            out.append((y1, "object"))
    return out


def _y_candidates(doc: LabelDocument, ids: Sequence[str], content_dots: int) -> list[tuple[int, str]]:
    cands = [(content_dots // 2, "center"), (0, "edge"), (content_dots, "edge")]
    cands += _object_candidates(doc, ids, "y")
    return cands


def _x_candidates(doc: LabelDocument, ids: Sequence[str],
                   length_dots: int | None) -> list[tuple[int, str]]:
    cands = [(0, "edge")]
    if length_dots is not None:
        cands.append((length_dots, "edge"))
        cands.append((length_dots // 2, "center"))
    cands += _object_candidates(doc, ids, "x")
    return cands


def _best_snap(edges: Sequence[int], candidates: Sequence[tuple[int, str]], threshold: int) -> int | None:
    best_key = None
    best_delta = None
    for edge_val in edges:
        for pos, kind in candidates:
            dist = pos - edge_val
            adist = abs(dist)
            if adist > threshold:
                continue
            key = (adist, _KIND_PRIORITY[kind])
            if best_key is None or key < best_key:
                best_key = key
                best_delta = dist
    return best_delta


def snap_move(doc: LabelDocument, ids: Sequence[str], dx: int, dy: int, *, content_dots: int,
              length_dots: int | None = None, grid: int = 1, threshold: int = SNAP_THRESHOLD,
              enabled: bool = True) -> SnapResult:
    if not enabled:
        return SnapResult(dx, dy, ())
    box = selection_box(doc, ids)
    if box is None:
        return SnapResult(dx, dy, ())
    x0, y0, x1, y1 = box
    mx0, my0, mx1, my1 = x0 + dx, y0 + dy, x1 + dx, y1 + dy

    x_cands = _x_candidates(doc, ids, length_dots)
    y_cands = _y_candidates(doc, ids, content_dots)
    x_edges = [mx0, (mx0 + mx1) // 2, mx1]
    y_edges = [my0, (my0 + my1) // 2, my1]

    x_delta = _best_snap(x_edges, x_cands, threshold)
    y_delta = _best_snap(y_edges, y_cands, threshold)

    final_dx, final_dy = dx, dy
    if x_delta is not None:
        final_dx = dx + x_delta
    elif grid > 1:
        target = round(mx0 / grid) * grid
        final_dx = dx + (target - mx0)
    if y_delta is not None:
        final_dy = dy + y_delta
    elif grid > 1:
        target = round(my0 / grid) * grid
        final_dy = dy + (target - my0)

    fx0, fy0 = x0 + final_dx, y0 + final_dy
    fx1, fy1 = x1 + final_dx, y1 + final_dy
    fx_edges = {fx0, (fx0 + fx1) // 2, fx1}
    fy_edges = {fy0, (fy0 + fy1) // 2, fy1}

    guides = []
    for pos, kind in x_cands:
        if pos in fx_edges:
            guides.append(Guide("v", pos, kind))
    for pos, kind in y_cands:
        if pos in fy_edges:
            guides.append(Guide("h", pos, kind))
    return SnapResult(final_dx, final_dy, tuple(dict.fromkeys(guides)))


def snap_resize(doc: LabelDocument, object_id: str, handle: str, dx: int, dy: int, *, content_dots: int,
                length_dots: int | None = None, grid: int = 1, threshold: int = SNAP_THRESHOLD,
                enabled: bool = True) -> SnapResult:
    if not enabled:
        return SnapResult(dx, dy, ())
    if handle not in _HANDLE_EDGES:
        raise ValueError(_t("Unbekannter Griff '{handle}' (erlaubt: {items})", handle=handle, items=', '.join(_HANDLE_EDGES)))
    obj = find_object(doc, object_id)
    x0, y0, x1, y1 = bbox(obj)
    edges = _HANDLE_EDGES[handle]

    final_dx, final_dy = dx, dy
    guides = []

    if "x0" in edges or "x1" in edges:
        base = x0 if "x0" in edges else x1
        moved = base + dx
        cands = _x_candidates(doc, [object_id], length_dots)
        delta = _best_snap([moved], cands, threshold)
        if delta is not None:
            final_dx = dx + delta
        elif grid > 1:
            target = round(moved / grid) * grid
            final_dx = dx + (target - moved)
        final_edge = moved + (final_dx - dx)
        for pos, kind in cands:
            if pos == final_edge:
                guides.append(Guide("v", pos, kind))

    if "y0" in edges or "y1" in edges:
        base = y0 if "y0" in edges else y1
        moved = base + dy
        cands = _y_candidates(doc, [object_id], content_dots)
        delta = _best_snap([moved], cands, threshold)
        if delta is not None:
            final_dy = dy + delta
        elif grid > 1:
            target = round(moved / grid) * grid
            final_dy = dy + (target - moved)
        final_edge = moved + (final_dy - dy)
        for pos, kind in cands:
            if pos == final_edge:
                guides.append(Guide("h", pos, kind))

    return SnapResult(final_dx, final_dy, tuple(dict.fromkeys(guides)))
