"""`FakeFacade` hat nachweislich dieselben Rückgabeformen wie die echte `LabelFacade`."""

import pytest

from automation_fakes import (DEFAULT_OUTCOME, FakeClock, FakeFacade, FakeNow, queued_job, status_json)
from daemon_fakes import FakeNow as DaemonNow
from tapesmith.automation.facade import LabelFacade
from tapesmith.ipc import codec
from tapesmith.status import PrinterStatus, StatusValue
from tapesmith.templates.store import find_template
from tapesmith.webapi import routes_templates
from tapesmith.webapi.labels import LabelNotPrintable
from webapi_fakes import close_ctx, make_ctx


def shape(obj):
    """Dicts auf Schlüssel, Listen auf das Muster des ersten Elements, Werte auf den Typnamen."""
    if isinstance(obj, dict):
        return {k: shape(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [shape(obj[0])] if obj else []
    if obj is None:
        return None
    return type(obj).__name__


def same_keys(fake, real) -> bool:
    """Rekursiver Schlüsselvergleich; None auf einer Seite gilt als erlaubt (optional)."""
    if fake is None or real is None:
        return True
    if isinstance(fake, dict) and isinstance(real, dict):
        return set(fake) == set(real) and all(same_keys(fake[k], real[k]) for k in fake)
    if isinstance(fake, list) and isinstance(real, list):
        return not fake or not real or same_keys(fake[0], real[0])
    return type(fake) is type(real) or {type(fake), type(real)} <= {int, float}


@pytest.fixture
def ctx(tmp_path):
    context = make_ctx(tmp_path, now=DaemonNow())
    context.service._debouncer._min_interval_s = 0
    yield context
    close_ctx(context)


@pytest.fixture
def real(ctx):
    return LabelFacade.from_ctx(ctx)


def test_state_shape(real):
    fake = FakeFacade().state()
    live = real.state()
    assert set(fake) == set(live)
    for key in ("state", "leased"):
        assert shape(fake)[key] == shape(live)[key]


def test_queue_shape(ctx, real):
    fake = FakeFacade().queue()
    assert set(fake) == set(real.queue())
    ctx.service.lease(object(), 60)
    out = real.print({"kind": "text", "lines": ["Wartet"]}, origin="api")
    assert out["status"] == "wartet"
    live_job = real.queue()["jobs"][0]
    assert set(queued_job(1)) == set(live_job)
    assert "last_error" in live_job and "error" not in live_job
    assert same_keys(queued_job(1), live_job)
    assert same_keys(fake, real.queue())


def test_status_values():
    fake = FakeFacade().status()
    assert fake["report"]["status"]["values"]["battery"]["value"] == 75
    assert fake["report"]["status"]["values"]["lid"]["value"] == "zu"
    assert status_json(status_none=True)["report"]["status"] is None
    assert "battery" not in status_json(battery=None)["report"]["status"]["values"]
    assert "lid" not in status_json(lid=None)["report"]["status"]["values"]


def test_status_default_exact():
    assert FakeFacade().status() == {
        "report": {"state": {"state": "verbunden", "transport": "COM4", "last_error": None, "leased": False},
                   "status": {"answered": True,
                              "values": {"battery": {"value": 75, "text": "75 %", "verified": True,
                                                     "raw": "1a0475"},
                                         "lid": {"value": "zu", "text": "zu", "verified": True,
                                                 "raw": "1a0598"}},
                              "unknown": [], "raw": ""},
                   "checked_at": "2026-09-28T10:00:00"},
        "view": {"chip": "P12 · verbunden (COM4) · Akku 75 %", "role": "success",
                 "title": "Tapesmith · verbunden", "detail": "", "tooltip": ""}}


def test_status_shape_against_real(real):
    fake = FakeFacade().status()
    live = real.status()
    assert set(fake) == set(live)
    assert set(fake["report"]) == set(live["report"])
    assert set(fake["view"]) == set(live["view"])
    assert set(fake["report"]["state"]) == set(live["report"]["state"])
    if live["report"]["status"] is not None:
        assert set(fake["report"]["status"]) == set(live["report"]["status"])


def test_status_shape_after_query(ctx, real):
    ctx.service.status(fresh=True)
    live = real.status()
    assert live["report"]["status"] is not None
    fake = FakeFacade().status()
    assert set(fake["report"]["status"]) == set(live["report"]["status"])
    live_values = live["report"]["status"]["values"]
    for kind in ("battery", "lid"):
        assert set(fake["report"]["status"]["values"][kind]) == set(live_values[kind])
        assert type(fake["report"]["status"]["values"][kind]["value"]) is type(live_values[kind]["value"])


def test_encode_status_keys():
    encoded = codec.encode_status(PrinterStatus(
        values={"battery": StatusValue("battery", 75, "75 %", True, b"")}, unknown=[], raw=b""))
    fake = status_json()["report"]["status"]
    assert set(encoded) == set(fake)
    assert set(encoded["values"]["battery"]) == set(fake["values"]["battery"])


def test_template_summary_shape():
    real_summary = routes_templates.template_summary_json(find_template("gefriergut"), set())
    fake = FakeFacade().template_summaries()[0]
    assert set(fake) == set(real_summary)
    assert fake["input_fields"]
    for item in fake["input_fields"]:
        assert set(item) == set(real_summary["input_fields"][0])
    assert same_keys(fake, real_summary)


def test_template_summaries_names_and_real(real):
    fake = FakeFacade()
    assert [t["name"] for t in fake.template_summaries()] == ["gefriergut", "eigentum"]
    assert [t["name"] for t in fake.template_summaries(["eigentum", "gibtsnicht"])] == ["eigentum"]
    live = real.template_summaries(["gefriergut", "eigentum"])
    for fake_t, live_t in zip(fake.template_summaries(), live):
        assert same_keys(fake_t, live_t)
        required = [f["id"] for f in fake_t["input_fields"] if f["required"]]
        assert required == [f["id"] for f in live_t["input_fields"] if f["required"]]


def test_outcome_and_render_shape(real):
    fake = FakeFacade()
    live_out = real.print({"kind": "text", "lines": ["Form"]}, origin="api")
    assert set(fake.print({}, origin="api")) == set(live_out) == set(DEFAULT_OUTCOME)
    live_render = real.render({"kind": "text", "lines": ["Form"]}, origin="api")
    assert same_keys(fake.render({}, origin="api"), live_render)


def test_history_shape_real_list(real):
    assert FakeFacade().history() == []
    assert isinstance(real.history(), list)


def test_fake_records_and_emits():
    fake = FakeFacade()
    seen = []
    fake.subscribe(lambda event, data: seen.append((event, data)))
    fake.print({"kind": "text", "lines": ["A"]}, {"copies": 2}, origin="mqtt")
    fake.render({"kind": "text", "lines": ["B"]}, origin="hotfolder")
    assert fake.printed == [({"kind": "text", "lines": ["A"]}, {"copies": 2}, "mqtt")]
    assert fake.rendered == [({"kind": "text", "lines": ["B"]}, None, "hotfolder")]
    fake.emit("job", {"phase": "fertig"})
    assert seen == [("job", {"phase": "fertig"})]
    fake.raise_on_print = RuntimeError("weg")
    with pytest.raises(RuntimeError):
        fake.print({}, origin="api")
    with pytest.raises(ValueError):
        fake.print({}, origin="quatsch")


def test_fake_defaults():
    fake = FakeFacade()
    assert fake.config() == {}
    assert fake.verified() == ("battery", "lid", "media", "serial", "firmware")
    assert fake.remaining_m() is None
    assert fake.preview_png({}, origin="api").startswith(b"\x89PNG")
    assert fake.print({}, origin="api") == DEFAULT_OUTCOME


def test_fake_preview_not_printable():
    fake = FakeFacade(render={"ok": False, "title": "", "errors": ["Kein Text"]})
    with pytest.raises(LabelNotPrintable):
        fake.preview_png({}, origin="api")


def test_fake_cancel_queued():
    fake = FakeFacade(queue={**FakeFacade().queue(), "jobs": [queued_job(1), queued_job(2)]})
    assert fake.cancel_queued(1) is True
    assert fake.cancel_queued(1) is False
    assert [j["id"] for j in fake.queue()["jobs"]] == [2]


def test_fake_clocks():
    clock = FakeClock(10.0)
    clock.advance(5)
    assert clock() == 15.0
    now = FakeNow()
    before = now()
    now.advance(minutes=3)
    assert (now() - before).total_seconds() == 180
