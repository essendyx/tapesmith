"""Druck- und Vorschau-Helfer der Web-API."""

import base64
import io

import pytest
from PIL import Image

from daemon_fakes import label
from tapesmith.jobs import JobMeta
from tapesmith.pipeline import CUT_PAUSE_OFF
from tapesmith.webapi.previews import empty_render, png_b64, preview_json
from tapesmith.webapi.printing import (PrintOptionsModel, build_request, options_from_json, plan_labels,
                                      submit_labels)
from webapi_fakes import close_ctx, make_ctx


@pytest.fixture
def ctx(tmp_path):
    ctx = make_ctx(tmp_path)
    yield ctx
    close_ctx(ctx)


def _meta(title="Hallo"):
    return JobMeta(source="gui", kind="text", title=title)


def _decode(text):
    return Image.open(io.BytesIO(base64.b64decode(text)))


def test_submit_ok(ctx):
    transport = ctx.service._test_transport
    out = submit_labels(ctx, [label(rows=40)], _meta(), PrintOptionsModel(job_key="abc_1"))
    assert out["status"] == "ok"
    assert out["history_id"] is not None
    assert out["job_key"] == "abc_1"
    assert out["title"] == "Hallo"
    assert isinstance(out["balance_text"], str)
    assert transport.written


def test_submit_generates_job_key(ctx):
    out = submit_labels(ctx, [label()], _meta(), PrintOptionsModel())
    assert len(out["job_key"]) == 32


def test_confirmation_and_on_done(ctx):
    done = []
    out = submit_labels(ctx, [label()], _meta(), PrintOptionsModel(copies=6), on_done=done.append)
    assert out["status"] == "bestätigung_nötig"
    assert out["reasons"]
    assert done == []
    out = submit_labels(ctx, [label()], _meta(), PrintOptionsModel(copies=6, confirmed=True),
                        on_done=done.append)
    assert out["status"] == "ok"
    assert len(done) == 1


def test_on_done_error_becomes_warning(ctx):
    def boom(outcome):
        raise RuntimeError("Zähler kaputt")

    out = submit_labels(ctx, [label()], _meta(), PrintOptionsModel(), on_done=boom)
    assert out["status"] == "ok"
    assert any("Zähler kaputt" in w for w in out["warnings"])


def test_enqueue_only_when_queue_enabled(tmp_path, monkeypatch):
    ctx = make_ctx(tmp_path, config={"queue": {"enabled": False}})
    try:
        calls = {}
        real = ctx.service.submit

        def spy(request, **kw):
            calls.update(kw)
            return real(request, **kw)

        monkeypatch.setattr(ctx.service, "submit", spy)
        submit_labels(ctx, [label()], _meta(), PrintOptionsModel(enqueue_on_offline=True))
        assert calls["enqueue_on_offline"] is False
    finally:
        close_ctx(ctx)


def test_options_from_json():
    assert options_from_json({}) == PrintOptionsModel()
    assert options_from_json(None) == PrintOptionsModel()
    opts = options_from_json({"copies": 2, "chain": True, "cut_pause_s": 0, "job_key": "Ab-9_x"})
    assert opts.copies == 2 and opts.chain is True and opts.cut_pause_s == 0 and opts.job_key == "Ab-9_x"
    for bad in ({"copies": 0}, {"copies": 1.5}, {"copies": True}, {"job_key": "a b"}, {"job_key": "x" * 65},
                {"cut_pause_s": -2}, {"cut_pause_s": "5"}, {"chain": "ja"}):
        with pytest.raises(ValueError):
            options_from_json(bad)


def test_build_request_cut_pause():
    req = build_request([label()], _meta(), options_from_json({"cut_pause_s": -1}))
    assert req.cut_pause_s == CUT_PAUSE_OFF
    req = build_request([label()], _meta(), options_from_json({}))
    assert req.cut_pause_s is None
    req = build_request([label()], _meta(), PrintOptionsModel(copies=3, chain=True, cut_marks=False))
    assert req.copies == 3 and req.chain and not req.cut_marks


def test_plan_labels(ctx):
    plan = plan_labels(ctx, [label()], _meta(), PrintOptionsModel(copies=2))
    assert plan.request.copies == 2


def test_preview_json(ctx):
    data = preview_json(ctx, [label()], _meta(), PrintOptionsModel(copies=3, chain=True),
                        extra_warnings=["Extra", "Extra"])
    design = _decode(data["design_png"])
    assert design.mode == "RGB" and design.height == ctx.profile().head_dots
    assert _decode(data["raster_png"]).mode == "1"
    assert data["width"] == design.width and data["height"] == design.height
    assert data["labels"] == 3 and data["jobs"] == 1
    assert data["balance_text"]
    assert data["warnings"].count("Extra") == 1
    assert set(data["decision"]) == {"allowed", "needs_confirmation", "reasons"}
    assert set(data) == {"design_png", "raster_png", "width", "height", "info", "content_mm", "tape_mm",
                         "labels", "jobs", "estimated", "balance_text", "decision", "warnings"}
    data = preview_json(ctx, [label()], _meta(), PrintOptionsModel(copies=6))
    assert data["decision"]["needs_confirmation"] is True


def test_png_b64_roundtrip():
    img = Image.new("1", (4, 3), 255)
    assert _decode(png_b64(img)).size == (4, 3)


def test_empty_render():
    data = empty_render("T", errors=["x"])
    assert data["ok"] is False and data["title"] == "T" and data["errors"] == ["x"]
    for key in ("warnings", "issues", "fixes", "shortened", "notes", "missing_secrets"):
        assert data[key] == []
    for key in ("preview", "font_size", "qr", "values", "tape_reason", "editor"):
        assert data[key] is None
