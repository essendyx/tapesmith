"""Ereignis-Broker, SSE-Format und SSE-Endpunkt."""

import asyncio
import threading

from daemon_fakes import label, wait_until
from tapesmith.jobs import JobMeta
from tapesmith.webapi import routes_core
from tapesmith.webapi.events import EventBroker, sse_format
from tapesmith.webapi.printing import PrintOptionsModel, submit_labels
from webapi_fakes import close_ctx, make_client, make_ctx


def test_two_subscribers_get_same_event():
    broker = EventBroker()
    a, b = broker.subscribe(), broker.subscribe()
    broker.publish("job", {"x": 1})
    assert a.get(1.0) == ("job", {"x": 1})
    assert b.get(1.0) == ("job", {"x": 1})


def test_full_queue_keeps_newest():
    broker = EventBroker()
    sub = broker.subscribe(maxsize=2)
    for i in range(3):
        broker.publish("e", {"i": i})
    assert sub.get(0.1) == ("e", {"i": 1})
    assert sub.get(0.1) == ("e", {"i": 2})
    assert sub.get(0.01) is None


def test_close_all_ends_get_immediately():
    broker = EventBroker()
    sub = broker.subscribe()
    result = {}

    def reader():
        result["value"] = sub.get(10.0)

    t = threading.Thread(target=reader)
    t.start()
    broker.close_all()
    t.join(2)
    assert not t.is_alive()
    assert result["value"] is None
    assert sub.closed
    assert sub.get(10.0) is None


def test_get_timeout_returns_none():
    sub = EventBroker().subscribe()
    assert sub.get(0.01) is None
    assert not sub.closed


def test_sse_format():
    assert sse_format("job", {"a": "ä"}) == 'event: job\ndata: {"a": "ä"}\n\n'


def test_subscriber_count():
    broker = EventBroker()
    assert broker.subscriber_count() == 0
    a = broker.subscribe()
    broker.subscribe()
    assert broker.subscriber_count() == 2
    a.close()
    assert broker.subscriber_count() == 1
    a.close()
    assert broker.subscriber_count() == 1
    broker.close_all()
    assert broker.subscriber_count() == 0


def test_sse_stream(tmp_path):
    client, ctx = make_client(tmp_path)

    def feeder():
        if not wait_until(lambda: ctx.broker.subscriber_count() >= 1, timeout=5):
            ctx.broker.close_all()          # Test scheitert, statt zu hängen
            return
        ctx.publish("queue", {})
        ctx.publish("job", {"job_key": "k", "phase": "fertig"})

    t = threading.Thread(target=feeder, daemon=True)
    t.start()
    try:
        with client.stream("GET", "/api/v1/events?t=test-token&limit=2") as r:
            assert r.status_code == 200
            assert r.headers["content-type"].startswith("text/event-stream")
            body = "".join(r.iter_text())
        t.join(5)
        names = [line.split(": ", 1)[1] for line in body.splitlines() if line.startswith("event: ")]
        assert names == ["hello", "queue", "job"]
        assert '"home_key"' in body
        assert ctx.broker.subscriber_count() == 0
    finally:
        close_ctx(ctx)


class _Req:
    def __init__(self):
        self.disconnected = False

    async def is_disconnected(self):
        return self.disconnected


async def _collect(gen):
    return [chunk async for chunk in gen]


def test_stream_logic_limit_excludes_hello():
    broker = EventBroker()
    sub = broker.subscribe()
    for i in range(3):
        broker.publish("e", {"i": i})
    chunks = asyncio.run(_collect(routes_core.event_stream(
        _Req(), sub, hello={"version": "v", "home_key": "h"}, limit=2, wait_s=0.01)))
    assert chunks[0].startswith("event: hello\n")
    assert len(chunks) == 3
    assert broker.subscriber_count() == 0 and sub.closed


def test_stream_logic_closed_subscription_ends():
    broker = EventBroker()
    sub = broker.subscribe()
    broker.publish("e", {})
    broker.close_all()
    chunks = asyncio.run(_collect(routes_core.event_stream(
        _Req(), sub, hello={}, limit=None, wait_s=0.01)))
    assert chunks[0].startswith("event: hello")
    assert broker.subscriber_count() == 0


def test_stream_logic_disconnect_and_ping():
    broker = EventBroker()
    sub = broker.subscribe()
    req = _Req()
    ticks = iter([0.0, 0.0, 20.0, 20.0, 20.0, 20.0])
    seen = []

    async def run():
        async for chunk in routes_core.event_stream(req, sub, hello={}, limit=None, wait_s=0.01,
                                                    clock=lambda: next(ticks, 40.0)):
            seen.append(chunk)
            if chunk.startswith(": ping"):
                req.disconnected = True

    asyncio.run(run())
    assert any(c == ": ping\n\n" for c in seen)
    assert broker.subscriber_count() == 0


def test_service_events_reach_broker(tmp_path):
    ctx = make_ctx(tmp_path)
    try:
        ctx.service.add_emitter(ctx.broker.publish)
        sub = ctx.broker.subscribe()
        meta = JobMeta(source="gui", kind="text", title="Hallo")
        out = submit_labels(ctx, [label()], meta, PrintOptionsModel(job_key="web1"))
        assert out["status"] == "ok"
        phases = []
        while True:
            item = sub.get(0.05)
            if item is None:
                break
            if item[0] == "job":
                assert item[1]["job_key"] == "web1"
                phases.append(item[1]["phase"])
        assert phases == ["angenommen", "läuft", "fertig"]
    finally:
        close_ctx(ctx)
