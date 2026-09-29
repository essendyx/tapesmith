"""Alle mitgelieferten Vorlagen, maschinell geprüft (Beispiel- und Grenzwerte):

(a) keine Tinte außerhalb des druckbaren Bereichs, kein Objekt außerhalb des Labels, Text überlappt
    keine anderen Objekte;
(b) Raster: zwischen Text und jedem Trennstrich bleibt mindestens der Innenabstand frei;
(c) nichts wird abgeschnitten (Text größer als seine Box ist ein Fehler, keine stille Kappung);
(d) Codes lassen sich rücklesen und halten längs zum Band ihre Ruhezone frei von fremder Tinte.
"""

from datetime import datetime

import pytest
from PIL import Image, ImageChops, ImageOps

from tapesmith.device.profile import load_profile
from tapesmith.document.from_spec import spec_to_document
from tapesmith.document.model import TextObject
from tapesmith.document.render import OUT_ACROSS, OUT_ALONG, render_document, render_object
from tapesmith.render import zxing
from tapesmith.render.barcode import QUIET_MODULES as CODE128_QUIET
from tapesmith.render.compose import mm_to_rows
from tapesmith.render.datamatrix import QUIET_MODULES as DM_QUIET
from tapesmith.render.qr import QUIET_MODULES as QR_QUIET
from tapesmith.templates.fill import CounterStore, resolve_values
from tapesmith.templates.lint import lint_values
from tapesmith.templates.render import render_template
from tapesmith.templates.store import builtin_templates

NOW = datetime(2026, 9, 27, 10, 0, 0)
PROFILE = load_profile()
BUILTIN = builtin_templates()
CASES = [(t, mode) for t in BUILTIN for mode in ("sample", "max")]


def _ink(image: Image.Image) -> Image.Image:
    """Tinte als Maske (255 = schwarz gedruckt)."""
    return ImageOps.invert(image.convert("L"))


def _rendered_document(template, mode, tmp_path, extra=None):
    values = lint_values(template, mode) | (extra or {})
    resolved = resolve_values(template, values, NOW, CounterStore(tmp_path / "c.json"))
    tr = render_template(template, resolved.values, PROFILE)
    if tr.document is not None:
        return tr, tr.document
    return tr, spec_to_document(tr.spec, PROFILE)


def _quiet(kind: str, module: int) -> int:
    if kind == "qr":
        return QR_QUIET * module
    if kind == "code128":
        return CODE128_QUIET * module
    return max(DM_QUIET * module, 2)


def check_document(doc, *, pad: int | None = None, cells=()):
    """Liefert eine Liste von Verstößen (leer = in Ordnung)."""
    problems: list[str] = []
    dr = render_document(doc, PROFILE)
    height = PROFILE.content_dots
    if dr.landscape.height != height:
        problems.append(f"Höhe {dr.landscape.height} statt {height}")
    for issue in dr.issues:
        if issue.level == "error" or issue.message in (OUT_ACROSS, OUT_ALONG):
            problems.append(f"{issue.object_id}: {issue.message}")

    length = dr.length_rows
    layers = {}
    for obj in doc.objects:
        if not obj.visible:
            continue
        rendered = render_object(obj, PROFILE)
        layer = Image.new("L", (length, height), 0)
        layer.paste(_ink(rendered.image), (obj.x, obj.y))
        layers[obj.id] = (obj, rendered, layer)

    # (a) Text überlappt keine fremde Tinte (invertierter Text liegt bewusst auf eigener Fläche).
    for oid, (obj, _rendered, layer) in layers.items():
        if not isinstance(obj, TextObject) or obj.invert:
            continue
        for other_id, (other, _r, other_layer) in layers.items():
            if other_id == oid:
                continue
            if ImageChops.multiply(layer, other_layer).getbbox() is not None:
                problems.append(f"{oid}: Text berührt {other_id}")

    # (d) Codes: rücklesbar, Ruhezone längs frei von fremder Tinte.
    for oid, code in dr.codes.items():
        if zxing.available() and not code.decodes:
            problems.append(f"{oid}: Code nicht rücklesbar")
        if code.inverted:
            continue
        obj, rendered, layer = layers[oid]
        box = layer.getbbox()
        if box is None:
            continue
        q = _quiet(code.kind, code.module_dots)
        others = Image.new("L", (length, height), 0)
        for other_id, (_o, _r, other_layer) in layers.items():
            if other_id != oid:
                others = ImageChops.lighter(others, other_layer)
        x0, y0, x1, y1 = box
        for zone in ((max(0, x0 - q), y0, x0, y1), (x1, y0, min(length, x1 + q), y1)):
            if zone[2] > zone[0] and others.crop(zone).getbbox() is not None:
                problems.append(f"{oid}: fremde Tinte in der Ruhezone ({q} Punkte)")

    # (b) Raster: Abstand Text zu Trennstrich.
    if pad is not None:
        land = _ink(dr.landscape)
        for left, right in cells:
            cell = land.crop((left, 0, right + 1, height))
            box = cell.getbbox()
            if box is None:
                continue
            if box[0] < pad or (right - left + 1) - box[2] < pad:
                problems.append(f"Zelle ab {left}: Text näher als {pad} Punkte am Trennstrich")
    return problems


def _raster_cells(doc):
    seps = sorted(o.x for o in doc.objects if o.kind == "line")
    return [(a + 2, b - 1) for a, b in zip(seps, seps[1:])]


@pytest.mark.parametrize("template,mode", CASES, ids=[f"{t.name}-{m}" for t, m in CASES])
def test_vorlage_geometrie(template, mode, tmp_path):
    _tr, doc = _rendered_document(template, mode, tmp_path)
    kwargs = {}
    if template.generator is not None and template.generator.name == "raster":
        kwargs = {"pad": mm_to_rows(1.0, PROFILE), "cells": _raster_cells(doc)}
    assert check_document(doc, **kwargs) == []


SIZE_CASES = [(t, s) for t in BUILTIN if t.text_size_field is not None
              for s in (("auto-feld", "2", "9") if t.text_size_per_field else ("2", "9"))]


@pytest.mark.parametrize("template,size", SIZE_CASES, ids=[f"{t.name}-{s}" for t, s in SIZE_CASES])
def test_alle_schriftgroessen(template, size, tmp_path):
    """Feste Größen (auch zu große) und "auto-feld": nie abgeschnitten, Abstände bleiben."""
    _tr, doc = _rendered_document(template, "max", tmp_path, {"schriftgroesse": size})
    kwargs = {}
    if template.text_size_per_field:
        kwargs = {"pad": mm_to_rows(1.0, PROFILE), "cells": _raster_cells(doc)}
    assert check_document(doc, **kwargs) == []


def test_pruefung_findet_text_am_trennstrich():
    """Gegenprobe: ein Raster ohne Innenabstand wird erkannt."""
    from tapesmith.document.generators.raster import PARAMS, generate
    out = generate(PARAMS | {"innenabstand_mm": 0.0}, {"belegung": "WWWWWWWW\nWWWWWWWW"}, PROFILE)
    problems = check_document(out.document, pad=mm_to_rows(1.0, PROFILE), cells=_raster_cells(out.document))
    assert any("Trennstrich" in p for p in problems)


RASTER = [t for t in BUILTIN if t.generator is not None and t.generator.name == "raster"]
LONG_ASSIGNMENT = "Kabelbinder-Sortiment\nW\n\nÄpfel-gjq\nserver01"


@pytest.mark.parametrize("template", RASTER, ids=lambda t: t.name)
@pytest.mark.parametrize("size", ["auto", "auto-feld", "9"])
def test_raster_grenzwerte_lange_namen(template, size, tmp_path):
    """Lange, schmale und breite Namen, Ober- und Unterlängen gemischt."""
    _tr, doc = _rendered_document(template, "sample", tmp_path,
                                  {"belegung": LONG_ASSIGNMENT, "schriftgroesse": size})
    assert check_document(doc, pad=mm_to_rows(1.0, PROFILE), cells=_raster_cells(doc)) == []
