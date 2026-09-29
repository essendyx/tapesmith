"""Tests für den `tape`-Parameter in `gui.preview_model.build_preview`/`design_image`."""

from tapesmith.device.profile import load_profile
from tapesmith.gui.preview_model import build_preview, plan_for_preview
from tapesmith.render.compose import LabelSpec, render_label
from tapesmith.tape.preview import CHECKER, tape_colors
from tapesmith.tape.profiles import find_tape

P = load_profile("p12")


def _plan():
    result = render_label(LabelSpec(lines=("pmx10",)), P)
    return plan_for_preview([result.head], P)


def test_ohne_tape_ist_bitgleich_zu_none():
    plan = _plan()
    data_default = build_preview(plan, P)
    data_none = build_preview(plan, P, None)
    assert data_default.design.tobytes() == data_none.design.tobytes()
    assert data_default.raster.tobytes() == data_none.raster.tobytes()
    assert "Band:" not in data_default.info


def test_mit_tape_faerbt_bedruckbaren_bereich():
    plan = _plan()
    tape = find_tape("weiss-schwarz")
    background, ink = tape_colors(tape)

    data_default = build_preview(plan, P)
    data_tape = build_preview(plan, P, tape)

    assert data_tape.raster.tobytes() == data_default.raster.tobytes()
    assert data_tape.info.endswith(f"Band: {tape.name}")

    design = data_tape.design
    printable_ys = _printable_ys()

    farben = {design.getpixel((x, y)) for y in printable_ys for x in range(design.width)}
    assert background in farben
    assert ink in farben


def _printable_ys() -> range:
    """y-Koordinaten im bedruckbaren Bereich der Landschaftsansicht: gleiche Abbildung
    x_head -> y = head_dots - 1 - x_head wie in `gui.preview_model._content_rgb`."""
    y_min = P.head_dots - P.content_offset - P.content_dots
    y_max = P.head_dots - 1 - P.content_offset
    return range(y_min, y_max + 1)


def test_transparentes_band_zeigt_schachbrett():
    plan = _plan()
    tape = find_tape("schwarz-transparent")
    data = build_preview(plan, P, tape)

    design = data.design
    printable_ys = _printable_ys()
    farben = {design.getpixel((x, y)) for y in printable_ys for x in range(design.width)}
    assert set(CHECKER) <= farben
