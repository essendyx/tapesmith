import dataclasses

import pytest
from PIL import Image

from tapesmith.device.profile import load_profile
from tapesmith.render.chain import (
    CUT_LINE_ROWS,
    DASH_DOTS,
    GAP_DOTS,
    ChainPlan,
    cut_mark,
    chain_preview,
    expand_copies,
    plan_chain,
    plan_single,
)
from tapesmith.render.compose import LabelSpec, mm_to_rows, render_label, rows_to_mm

P = dataclasses.replace(load_profile(), leader_mm=8.0, trailer_mm=16.0)


def head(rows: int, fill: int = 255) -> Image.Image:
    return Image.new("1", (96, rows), fill)


# 1. expand_copies -----------------------------------------------------------

def test_expand_copies_repeats_each_head_in_order():
    a, b = head(10), head(20)
    result = expand_copies([a, b], 2)
    assert result == [a, a, b, b]
    assert result[0] is a and result[1] is a and result[2] is b and result[3] is b


def test_expand_copies_rejects_zero_or_negative():
    with pytest.raises(ValueError, match="Kopien müssen"):
        expand_copies([head(10)], 0)


# 2. cut_mark ------------------------------------------------------------------

def test_cut_mark_geometry(pixel_colors):
    mark = cut_mark(P)
    gap_rows = mm_to_rows(1.0, P)
    assert mark.height == 2 * gap_rows + CUT_LINE_ROWS
    assert mark.width == P.head_dots

    left = mark.crop((0, 0, P.content_offset, mark.height))
    assert pixel_colors(left) == {255}
    if P.content_offset + P.content_dots < mark.width:
        right = mark.crop((P.content_offset + P.content_dots, 0, mark.width, mark.height))
        assert pixel_colors(right) == {255}

    line_row = gap_rows
    assert mark.getpixel((P.content_offset, line_row)) == 0
    assert mark.getpixel((P.content_offset + DASH_DOTS, line_row)) == 255

    outside_row = mark.crop((0, 0, mark.width, gap_rows))
    assert pixel_colors(outside_row) == {255}
    outside_row2 = mark.crop((0, gap_rows + CUT_LINE_ROWS, mark.width, mark.height))
    assert pixel_colors(outside_row2) == {255}


# 3. plan_chain merges into one job with savings -------------------------------

def test_plan_chain_merges_three_labels_into_one_job():
    heads = [head(240), head(240), head(240)]
    plan = plan_chain(heads, P)
    assert len(plan.jobs) == 1
    job = plan.jobs[0]
    assert job.head.height == 3 * 240 + 2 * 18
    assert job.label_indices == (0, 1, 2)
    assert plan.chained is True

    assert plan.balance.single_mm == pytest.approx(3 * (30 + 24))
    assert plan.balance.chain_mm == pytest.approx(rows_to_mm(756, P) + 24)
    assert plan.balance.saved_mm > 0

    text = plan.balance.text()
    assert text.startswith("3 Labels:")
    assert "statt" in text
    assert "gespart" in text


# 4. plan_chain splits long chain into several jobs ----------------------------

def test_plan_chain_splits_into_jobs_at_max_length():
    heads = [head(240) for _ in range(10)]
    plan = plan_chain(heads, P, max_job_mm=200.0)
    assert len(plan.jobs) == 2
    for job in plan.jobs:
        assert rows_to_mm(job.head.height, P) <= 200.0
    all_indices = [i for job in plan.jobs for i in job.label_indices]
    assert all_indices == list(range(10))
    assert any("auf 2 Jobs aufgeteilt" in w for w in plan.warnings)


# 5. one label longer than max_job_mm gets its own job --------------------------

def test_plan_chain_isolates_label_longer_than_max():
    heads = [head(240), head(1760), head(240)]
    plan = plan_chain(heads, P, max_job_mm=200.0)
    long_jobs = [job for job in plan.jobs if job.label_indices == (1,)]
    assert len(long_jobs) == 1
    assert long_jobs[0].head.height == 1760
    assert any("wird einzeln gedruckt" in w for w in plan.warnings)


# 6. cut_marks=False keeps length but leaves separator blank -------------------

def test_plan_chain_without_cut_marks_keeps_length_but_blank(pixel_colors):
    heads = [head(240), head(240)]
    with_marks = plan_chain(heads, P)
    without_marks = plan_chain(heads, P, cut_marks=False)
    assert with_marks.jobs[0].head.height == without_marks.jobs[0].head.height

    separator = without_marks.jobs[0].head.crop((0, 240, 96, 240 + 18))
    assert pixel_colors(separator) == {255}


# 7. content offsets are preserved inside the job image -------------------------

def test_plan_chain_preserves_label_content_positions():
    h1 = head(240)
    h1.putpixel((50, 0), 0)
    h2 = head(240)
    h2.putpixel((50, 0), 0)
    plan = plan_chain([h1, h2], P)
    job = plan.jobs[0].head
    assert job.getpixel((50, 0)) == 0
    assert job.getpixel((50, 240 + 18)) == 0


# 8. plan_single: each label its own job, no savings ----------------------------

def test_plan_single_gives_each_label_its_own_job():
    a, b = head(240), head(480)
    plan = plan_single([a, b], P)
    assert len(plan.jobs) == 2
    assert plan.chained is False
    assert plan.balance.chain_mm == pytest.approx(plan.balance.single_mm)
    assert "(2 Jobs)" in plan.balance.text()


# 9. single label balance text ---------------------------------------------------

def test_single_label_balance_text():
    plan = plan_chain([head(240)], P)
    assert plan.chained is False
    mm = rows_to_mm(240, P) + P.leader_mm + P.trailer_mm
    assert plan.balance.text() == f"1 Label: {mm:.0f} mm Band"


# 10. validation errors -----------------------------------------------------------

def test_plan_chain_rejects_empty_list():
    with pytest.raises(ValueError, match="Keine Labels"):
        plan_chain([], P)


def test_plan_chain_rejects_wrong_width():
    wrong = Image.new("1", (80, 240), 255)
    with pytest.raises(ValueError):
        plan_chain([wrong], P)


# 11. chain_preview dimensions ----------------------------------------------------

def test_chain_preview_dimensions():
    heads = [head(240) for _ in range(10)]
    plan = plan_chain(heads, P, max_job_mm=200.0)
    preview = chain_preview(plan, P, scale=2)

    assert preview.height == P.head_dots * 2

    lead = mm_to_rows(P.leader_mm, P)
    trail = mm_to_rows(P.trailer_mm, P)
    expected = 2 * sum(lead + job.head.height + trail for job in plan.jobs)
    expected += 2 * 4 * (len(plan.jobs) - 1)
    assert preview.width == expected


# 12. snapshot ----------------------------------------------------------------------

def test_chain_preview_snapshot(snapshot):
    label = render_label(LabelSpec(lines=("SSD-1",), max_length_mm=30), P)
    heads = expand_copies([label.head], 3)
    plan = plan_chain(heads, P)
    preview = chain_preview(plan, P)
    snapshot("chain-3x-ssd", preview)
