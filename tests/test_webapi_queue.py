"""Warteschlange über die Web-API, inklusive Auto-Nachdruck ohne Dienst-Neustart."""

import pytest

from webapi_fakes import close_ctx, make_client


@pytest.fixture
def api(tmp_path):
    client, ctx = make_client(tmp_path)
    yield client, ctx
    close_ctx(ctx)


def _enqueue(ctx, *, title: str = "Wartend", sensitive: bool = False) -> int:
    return ctx.service.queue.add({"request": {}}, source="gui", title=title, sensitive=sensitive)


def test_queue_snapshot_and_actions(api):
    client, ctx = api
    job_id = _enqueue(ctx, title="Auftrag A")

    r = client.get("/api/v1/queue")
    assert r.status_code == 200
    body = r.json()
    assert [j["id"] for j in body["jobs"]] == [job_id]
    assert body["paused"] is False

    r = client.post(f"/api/v1/queue/{job_id}/duplicate", json={})
    assert r.status_code == 200
    new_id = r.json()["id"]
    assert new_id != job_id

    r = client.post(f"/api/v1/queue/{new_id}/move", json={"position": 0})
    assert r.status_code == 200
    assert r.json() == {}
    snapshot = client.get("/api/v1/queue").json()
    assert snapshot["jobs"][0]["id"] == new_id

    r = client.post(f"/api/v1/queue/{job_id}/cancel", json={})
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    snapshot = client.get("/api/v1/queue").json()
    assert job_id not in [j["id"] for j in snapshot["jobs"]]

    r = client.post("/api/v1/queue/pause", json={})
    assert r.status_code == 200
    assert client.get("/api/v1/queue").json()["paused"] is True

    r = client.post("/api/v1/queue/resume", json={})
    assert r.status_code == 200
    assert client.get("/api/v1/queue").json()["paused"] is False


def test_route_order_retry_all_and_inventory_search(api):
    """Feste Pfade vor Parameterpfaden (Routenreihenfolge):
    `/queue/retry-all` darf nicht als `/queue/{id}/...` interpretiert werden, `/inventory/search`
    nicht als Box-ID unter `/inventory/boxes/{id}`-artigen Routen."""
    client, _ctx = api
    r = client.post("/api/v1/queue/retry-all", json={})
    assert r.status_code == 200 and r.json() == {}

    r = client.get("/api/v1/inventory/search", params={"q": "x"})
    assert r.status_code == 200
    assert r.json() == {"hits": []}


def test_queue_retry_all(api):
    client, ctx = api
    _enqueue(ctx, title="Auftrag A")
    _enqueue(ctx, title="Auftrag B")
    r = client.post("/api/v1/queue/retry-all", json={})
    assert r.status_code == 200 and r.json() == {}


def test_queue_unknown_id_cancel_returns_ok_false(api):
    """Kernverhalten: `queue_cancel` wirft nie, unbekannte ID -> ok:false (Abweichung vom
    generischen 404-Muster anderer Warteschlangen-Aktionen)."""
    client, _ctx = api
    r = client.post("/api/v1/queue/9999/cancel", json={})
    assert r.status_code == 200
    assert r.json() == {"ok": False}


def test_queue_unknown_id_duplicate_retry_move_are_404(api):
    client, _ctx = api
    r = client.post("/api/v1/queue/9999/duplicate", json={})
    assert r.status_code == 404
    assert r.json()["error"]["kind"] == "NotFound"

    r = client.post("/api/v1/queue/9999/retry", json={})
    assert r.status_code == 404

    r = client.post("/api/v1/queue/9999/move", json={"position": 0})
    assert r.status_code == 404


class FakeRunner:
    """Minimaler Ersatz für `daemon.runner.QueueRunner`, wie ihn `PrintService.attach_runner`
    erwartet (nur die von `queue_snapshot`/`close` gebrauchten Attribute/Methoden)."""

    probe_name = "none"
    last_reason = ""

    def __init__(self):
        self.reconfigure_calls: list[dict] = []
        self.auto_retry = True

    def reconfigure(self, cfg: dict) -> None:
        self.reconfigure_calls.append(cfg)
        self.auto_retry = bool(cfg.get("queue", {}).get("auto_retry", True))

    def next_try(self):
        return None

    def wake(self, manual: bool = False) -> None:
        pass

    def stop(self) -> None:
        pass


def test_auto_retry_toggles_without_restart(tmp_path):
    client, ctx = make_client(tmp_path)
    try:
        runner = FakeRunner()
        ctx.service.attach_runner(runner)
        sub = ctx.broker.subscribe()

        r = client.put("/api/v1/queue/auto-retry", json={"on": False})
        assert r.status_code == 200
        body = r.json()
        assert body["auto_retry"] is False

        assert ctx.service.config["queue"]["auto_retry"] is False
        assert runner.reconfigure_calls and runner.reconfigure_calls[-1]["queue"]["auto_retry"] is False

        item = sub.get(2.0)
        assert item is not None
        event, data = item
        assert event == "config" and data["keys"] == ["queue.auto_retry"]
    finally:
        close_ctx(ctx)


def test_auto_retry_toggles_while_job_lock_held(tmp_path):
    client, ctx = make_client(tmp_path)
    try:
        ctx.service._job_lock.acquire()
        try:
            r = client.put("/api/v1/queue/auto-retry", json={"on": False})
            assert r.status_code == 200
            assert r.json()["auto_retry"] is False
        finally:
            ctx.service._job_lock.release()
    finally:
        close_ctx(ctx)
