"""Tests für das Vorschau-Modell (WYSIWYG, ohne Qt)."""

import subprocess
import sys

import pytest
from PIL import Image

from tapesmith.device.profile import load_profile
from tapesmith.pipeline import PrintLabel, PrintPipeline, PrintRequest
from tapesmith.jobs import JobMeta
from tapesmith.render.chain import TapeBalance
from tapesmith.render.compose import LabelSpec, mm_to_rows, render_label

from tapesmith.gui.preview_model import build_preview, info_text, plan_for_preview

P = load_profile("p12")


def test_kein_qt_import():
    result = subprocess.run(
        [sys.executable, "-c", "import tapesmith.gui.preview_model, sys; "
                                "assert 'PySide6' not in sys.modules"],
        cwd="src", capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_wysiwyg_druckbild_ist_gesendete_bytes():
    result = render_label(LabelSpec(lines=("pmx10 SSD-1",)), P)
    plan = plan_for_preview([result.head], P)
    data = build_preview(plan, P)

    assert len(data.raster_jobs) == 1
    assert data.raster_jobs[0].rotate(-90, expand=True).tobytes() == plan.jobs[0].head.tobytes()
    assert plan.jobs[0].head.tobytes() == result.head.tobytes()


def test_planung_wie_pipeline_kopien_und_kette():
    result = render_label(LabelSpec(lines=("pmx10 SSD-1",)), P)
    pipeline = PrintPipeline(P, run_session=lambda fn: None)

    req = PrintRequest(labels=(PrintLabel(result.head),), meta=JobMeta(source="gui", kind="text"),
                        copies=3, chain=True)
    pp = pipeline.plan(req)
    cp = plan_for_preview([result.head], P, copies=3, chain=True)

    assert [j.head.tobytes() for j in pp.chain.jobs] == [j.head.tobytes() for j in cp.jobs]
    assert pp.balance_text == cp.balance.text()

    req2 = PrintRequest(labels=(PrintLabel(result.head),), meta=JobMeta(source="gui", kind="text"),
                         copies=2, chain=False)
    pp2 = pipeline.plan(req2)
    cp2 = plan_for_preview([result.head], P, copies=2, chain=False)

    assert [j.head.tobytes() for j in pp2.chain.jobs] == [j.head.tobytes() for j in cp2.jobs]
    assert len(pp2.chain.jobs) == len(cp2.jobs) == 2


def test_info_text_formatiert_ca_und_geschaetzt():
    text = info_text(38.2, 305, 24.0, 62.2, True)
    assert text == "Inhalt 38 mm (305 Punkte) + Vor-/Nachlauf ca. 24 mm = ca. 62 mm Band (geschätzt)"

    text_ohne = info_text(38.2, 305, 24.0, 62.2, False)
    assert text_ohne == "Inhalt 38 mm (305 Punkte) + Vor-/Nachlauf ca. 24 mm = ca. 62 mm Band"
    assert "geschätzt" not in text_ohne

    balance = TapeBalance(labels=4, jobs=1, chain_mm=100, single_mm=160)
    text_bilanz = info_text(38.2, 305, 24.0, 62.2, True, balance=balance)
    assert text_bilanz.endswith(" · 4 Labels: 100 mm statt 160 mm (60 mm gespart)")


def test_build_preview_einzel_label():
    result = render_label(LabelSpec(lines=("pmx10 SSD-1",)), P)
    plan = plan_for_preview([result.head], P)
    data = build_preview(plan, P)

    assert data.estimated is True
    assert data.tape_mm == plan.balance.chain_mm
    assert data.leader_trailer_mm == P.leader_mm + P.trailer_mm
    assert data.content_dots == result.head.height


def test_design_bild_zonen():
    result = render_label(LabelSpec(lines=("pmx10 SSD-1",)), P)
    plan = plan_for_preview([result.head], P)
    data = build_preview(plan, P)

    lead = mm_to_rows(P.leader_mm, P)
    trail = mm_to_rows(P.trailer_mm, P)
    design = data.design

    assert design.size == (lead + result.head.height + trail, P.head_dots)
    assert design.getpixel((0, 40)) == (90, 90, 90)  # "cut"
    assert design.getpixel((2, 40)) == (200, 200, 200)  # "leader"
    assert design.getpixel((design.width - 1, 40)) == (90, 90, 90)  # "cut"

    randzeile = design.getpixel((lead + 2, P.head_dots - 1))
    assert randzeile in ((225, 225, 225), (170, 170, 170))  # "margin" oder "hatch"

    landscape_invertiert = result.head.rotate(90, expand=True)
    ink_mask = landscape_invertiert.point(lambda p: 255 if p == 0 else 0)
    ink_px = ink_mask.load()
    ink_x, ink_y = next((x, y) for y in range(ink_mask.height) for x in range(ink_mask.width)
                         if ink_px[x, y])
    assert design.getpixel((lead + ink_x, ink_y)) == (0, 0, 0)  # "ink"


def test_kette_kopien_und_bilanz():
    head = Image.new("1", (P.head_dots, mm_to_rows(10.0, P)), 255)
    plan = plan_for_preview([head], P, copies=4, chain=True)
    data = build_preview(plan, P)

    assert data.labels == 4
    assert data.jobs == 1
    assert "4 Labels" in data.info
    assert "gespart" in data.info

    lang = render_label(LabelSpec(lines=("x",), fixed_length_mm=60.0), P)
    plan2 = plan_for_preview([lang.head], P, copies=5, chain=True)
    data2 = build_preview(plan2, P)

    assert data2.jobs == 2
    erwartete_breite = sum(job.head.height for job in plan2.jobs) + (data2.jobs - 1) * 6
    assert data2.raster.width == erwartete_breite


def test_copies_kleiner_1_wirft():
    result = render_label(LabelSpec(lines=("x",)), P)
    with pytest.raises(ValueError):
        plan_for_preview([result.head], P, copies=0)
