"""`automation.facade.LabelFacade` über einen echten Dienst mit MemoryTransport."""

import io

import pytest
from PIL import Image

from daemon_fakes import FakeNow
from tapesmith.automation.facade import LabelFacade
from tapesmith.webapi.labels import LabelNotPrintable
from webapi_fakes import close_ctx, make_ctx

TEXT = {"kind": "text", "lines": ["X"]}


@pytest.fixture
def ctx(tmp_path):
    context = make_ctx(tmp_path, now=FakeNow())
    context.service._debouncer._min_interval_s = 0
    yield context
    close_ctx(context)


@pytest.fixture
def facade(ctx):
    return LabelFacade.from_ctx(ctx)


def test_from_ctx(ctx, facade):
    assert facade.ctx is ctx


def test_render(facade):
    out = facade.render(TEXT, origin="api")
    assert out["ok"] is True
    assert out["preview"]["design_png"]


def test_render_unknown_origin(facade):
    with pytest.raises(ValueError):
        facade.render(TEXT, origin="quatsch")


def test_print_with_origin(ctx, facade):
    out = facade.print(TEXT, origin="mqtt")
    assert out["status"] == "ok"
    entry = ctx.history().get(out["history_id"])
    assert entry.source == "mqtt"


def test_print_not_printable(facade):
    with pytest.raises(LabelNotPrintable):
        facade.print({"kind": "text", "lines": [""]}, origin="api")


def test_print_options(facade):
    out = facade.print(TEXT, {"copies": 2}, origin="api")
    assert out["status"] == "ok"


def test_preview_png(facade):
    data = facade.preview_png(TEXT, origin="api")
    assert data.startswith(b"\x89PNG")
    raster = facade.preview_png(TEXT, origin="api", raster=True)
    assert raster.startswith(b"\x89PNG")
    assert Image.open(io.BytesIO(raster)).mode == "1"


def test_preview_png_not_printable(facade):
    with pytest.raises(LabelNotPrintable):
        facade.preview_png({"kind": "text", "lines": [""]}, origin="api")


def test_template_summaries(facade):
    out = facade.template_summaries(["gefriergut", "gibtsnicht", "eigentum"])
    assert [t["name"] for t in out] == ["gefriergut", "eigentum"]
    assert out[0]["input_fields"]


def test_template_summaries_all_and_path_names(facade):
    names = [t["name"] for t in facade.template_summaries()]
    assert "gefriergut" in names and "eigentum" in names
    assert facade.template_summaries(["../gefriergut", "C:\\x"]) == []


def test_template_summaries_favorites(ctx, facade):
    from tapesmith import config as config_mod
    config_mod.save_config({"gui": {"favorites": ["eigentum"]}})
    out = facade.template_summaries(["gefriergut", "eigentum"])
    assert [t["favorite"] for t in out] == [False, True]


def test_state_queue_history_verified(facade):
    assert set(facade.state()) == {"state", "transport", "last_error", "leased"}
    assert "jobs" in facade.queue()
    facade.print(TEXT, origin="api")
    history = facade.history(5)
    assert isinstance(history, list) and history
    assert history[0]["source"] == "api"
    assert facade.history(5, "gibtsganzsichernicht") == []
    assert "lid" in facade.verified()


def test_status_from_cache(facade):
    out = facade.status()
    assert set(out) == {"report", "view"}
    assert set(out["report"]) == {"state", "status", "checked_at"}


def test_queue_and_cancel(ctx, facade):
    ctx.service.lease(object(), 60)
    out = facade.print(TEXT, origin="api")
    assert out["status"] == "wartet"
    jobs = facade.queue()["jobs"]
    assert [j["id"] for j in jobs] == [out["queue_id"]]
    assert "last_error" in jobs[0] and "error" not in jobs[0]
    assert facade.cancel_queued(out["queue_id"]) is True
    assert facade.queue()["jobs"] == []


def test_remaining_m(facade, ctx):
    assert facade.remaining_m() is None
    ctx.service.rolls.remaining_mm = lambda *a, **k: 2500.0
    assert facade.remaining_m() == 2.5


def test_subscribe(facade):
    seen = []
    facade.subscribe(lambda event, data: seen.append(event))
    facade.print(TEXT, origin="api")
    assert "job" in seen


def test_config(facade):
    cfg = facade.config()
    assert isinstance(cfg, dict) and cfg.get("transport") == "memory"


def test_without_ctx(ctx):
    facade = LabelFacade(ctx.service)
    assert facade.ctx is not ctx
    assert facade.ctx.service is ctx.service
    assert facade.render(TEXT, origin="api")["ok"] is True
    out = facade.print({"kind": "text", "lines": ["Ohne Kontext"]}, origin="hotfolder")
    assert out["status"] == "ok"
