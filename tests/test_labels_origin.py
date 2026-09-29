"""Quelle (`origin`) je Auftrag und Label-Quelle `image` in `webapi.labels`."""

import base64
import io

import pytest
from PIL import Image

from daemon_fakes import FakeNow
from tapesmith.templates import gallery as gallery_mod
from tapesmith.templates.store import find_template
from tapesmith.webapi import labels, routes_templates
from tapesmith.webapi.labels import print_source, resolve
from tapesmith.webapi.printing import options_from_json
from webapi_fakes import close_ctx, make_ctx

TEXT = {"kind": "text", "lines": ["A"]}


@pytest.fixture
def ctx(tmp_path):
    context = make_ctx(tmp_path, now=FakeNow())
    yield context
    close_ctx(context)


def _png_b64(size=(40, 20), *, black=True) -> str:
    img = Image.new("RGB", size, (255, 255, 255))
    if black:
        img.paste((0, 0, 0), (5, 5, 35, 15))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def test_origin_sets_meta_source(ctx):
    assert resolve(ctx, TEXT, origin="mcp").meta.source == "mcp"
    assert resolve(ctx, TEXT).meta.source == "gui"


def test_unknown_origin_raises(ctx):
    with pytest.raises(ValueError):
        resolve(ctx, TEXT, origin="quatsch")


def test_template_origin(ctx):
    values = gallery_mod.sample_values(find_template("gefriergut"))
    resolved = resolve(ctx, {"kind": "template", "template": "gefriergut", "values": values},
                       origin="hotfolder")
    assert resolved.ok, resolved.errors
    assert resolved.meta.source == "hotfolder"


def test_print_source_origin_in_history(ctx):
    out = print_source(ctx, TEXT, options_from_json(None), origin="api")
    assert out["status"] == "ok"
    entry = ctx.history().last()
    assert entry is not None and entry.source == "api"


def test_image_source_ok(ctx):
    resolved = resolve(ctx, {"kind": "image", "png": _png_b64(), "name": "Logo"}, origin="api")
    assert resolved.ok, resolved.errors
    assert len(resolved.labels) == 1
    assert resolved.labels[0].head.width == ctx.profile().head_dots
    assert resolved.title == "Logo"
    assert resolved.meta.source == "api" and resolved.meta.kind == "image"
    assert resolved.fixes == [] and resolved.qr is None


def test_image_default_title(ctx):
    resolved = resolve(ctx, {"kind": "image", "png": _png_b64()})
    assert resolved.title == "Bild"
    assert resolved.meta.source == "gui"


def test_image_broken_base64(ctx):
    with pytest.raises(ValueError):
        resolve(ctx, {"kind": "image", "png": "@@@kein base64@@@"})


def test_image_not_an_image(ctx):
    data = base64.b64encode(b"das ist kein Bild").decode("ascii")
    resolved = resolve(ctx, {"kind": "image", "png": data})
    assert resolved.ok is False
    assert any("Bild nicht lesbar" in e for e in resolved.errors)


@pytest.mark.parametrize("extra", [
    {"threshold": 300}, {"threshold": -1}, {"threshold": 12.5}, {"threshold": True},
    {"rotate": "schief"}, {"fit": "ja"}, {"name": 5}, {"png": 5},
])
def test_image_bad_fields(ctx, extra):
    with pytest.raises(ValueError):
        resolve(ctx, {"kind": "image", "png": _png_b64(), **extra})


def test_image_missing_png(ctx):
    with pytest.raises(ValueError):
        resolve(ctx, {"kind": "image"})


def test_image_too_large(ctx, monkeypatch):
    monkeypatch.setattr(labels, "IMAGE_MAX_BYTES", 10)
    with pytest.raises(ValueError):
        resolve(ctx, {"kind": "image", "png": _png_b64()})


def test_image_options(ctx):
    resolved = resolve(ctx, {"kind": "image", "png": _png_b64(), "threshold": 10, "rotate": "none",
                             "fit": True})
    assert resolved.ok, resolved.errors


def test_image_render_json(ctx):
    out = labels.render_json(ctx, resolve(ctx, {"kind": "image", "png": _png_b64()}),
                             options_from_json(None))
    assert out["ok"] is True and out["preview"] is not None


def test_export_source_origin(ctx):
    data, media, _name = labels.export_source(ctx, TEXT, options_from_json(None), "png", origin="mcp")
    assert media == "image/png" and data.startswith(b"\x89PNG")


def test_template_summary_alias():
    assert routes_templates.template_summary_json is routes_templates._summary_json
