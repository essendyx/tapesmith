"""Inventar über die Web-API: Boxen, Gegenstände, Suche, Verleih, Labels."""

from datetime import date, timedelta

import pytest

from webapi_fakes import close_ctx, make_client


@pytest.fixture
def api(tmp_path):
    client, ctx = make_client(tmp_path)
    yield client, ctx
    close_ctx(ctx)


def test_box_and_item_search(api):
    client, _ctx = api
    r = client.post("/api/v1/inventory/boxes", json={"id": "BOX-07", "location": "Regal 3"})
    assert r.status_code == 200
    assert r.json() == {"id": "BOX-07", "location": "Regal 3", "note": "",
                        "created": r.json()["created"], "items": 0}

    r = client.post("/api/v1/inventory/items", json={"name": "HDMI-Adapter", "box_id": "BOX-07"})
    assert r.status_code == 200
    item = r.json()
    assert item["name"] == "HDMI-Adapter" and item["box_id"] == "BOX-07"

    r = client.get("/api/v1/inventory/search", params={"q": "hdmi"})
    assert r.status_code == 200
    hits = r.json()["hits"]
    assert len(hits) == 1
    assert "BOX-07" in hits[0]["text"]
    assert hits[0]["box"]["id"] == "BOX-07"

    r = client.get("/api/v1/inventory/boxes")
    assert r.status_code == 200
    boxes = {b["id"]: b for b in r.json()["boxes"]}
    assert boxes["BOX-07"]["items"] == 1


def test_box_duplicate_is_422_and_unknown_is_404(api):
    client, _ctx = api
    client.post("/api/v1/inventory/boxes", json={"id": "BOX-01", "location": "A"})
    r = client.post("/api/v1/inventory/boxes", json={"id": "BOX-01", "location": "B"})
    assert r.status_code == 422

    r = client.get("/api/v1/inventory/boxes/UNBEKANNT")
    assert r.status_code == 404
    assert r.json()["error"]["kind"] == "NotFound"

    r = client.put("/api/v1/inventory/boxes/UNBEKANNT", json={"note": "x"})
    assert r.status_code == 404

    r = client.delete("/api/v1/inventory/boxes/UNBEKANNT")
    assert r.status_code == 404


def test_box_detail_and_update(api):
    client, _ctx = api
    client.post("/api/v1/inventory/boxes", json={"id": "BOX-02", "location": "Keller"})
    client.post("/api/v1/inventory/items", json={"name": "Kabel", "box_id": "BOX-02", "qty": 3})

    r = client.get("/api/v1/inventory/boxes/BOX-02")
    assert r.status_code == 200
    body = r.json()
    assert body["items"] == 1
    assert body["item_list"][0]["name"] == "Kabel"
    assert body["item_list"][0]["qty"] == 3

    r = client.put("/api/v1/inventory/boxes/BOX-02", json={"note": "wichtig"})
    assert r.status_code == 200
    assert r.json()["note"] == "wichtig"
    assert r.json()["location"] == "Keller"


def test_item_move_and_delete(api):
    client, _ctx = api
    client.post("/api/v1/inventory/boxes", json={"id": "BOX-A", "location": "1"})
    client.post("/api/v1/inventory/boxes", json={"id": "BOX-B", "location": "2"})
    item = client.post("/api/v1/inventory/items", json={"name": "Maus", "box_id": "BOX-A"}).json()

    r = client.put(f"/api/v1/inventory/items/{item['id']}", json={"box_id": "BOX-B"})
    assert r.status_code == 200
    assert r.json()["box_id"] == "BOX-B"

    r = client.delete(f"/api/v1/inventory/items/{item['id']}")
    assert r.status_code == 200 and r.json() == {}

    r = client.delete(f"/api/v1/inventory/items/{item['id']}")
    assert r.status_code == 404


def test_loans(api):
    client, ctx = api
    yesterday = (ctx.now().date() - timedelta(days=1)).isoformat()

    r = client.post("/api/v1/inventory/loans",
                    json={"item": "Bohrmaschine", "person": "Nachbar", "due": yesterday})
    assert r.status_code == 200
    loan = r.json()
    assert loan["open"] is True
    assert loan["overdue"] is True

    r = client.get("/api/v1/inventory/loans", params={"open": "true"})
    assert r.status_code == 200
    assert len(r.json()["loans"]) == 1

    r = client.post(f"/api/v1/inventory/loans/{loan['id']}/return", json={})
    assert r.status_code == 200
    assert r.json()["open"] is False

    r = client.get("/api/v1/inventory/loans", params={"open": "true"})
    assert r.json()["loans"] == []

    r = client.post("/api/v1/inventory/loans/9999/return", json={})
    assert r.status_code == 404


def test_labels_render_and_print(api):
    client, _ctx = api
    client.post("/api/v1/inventory/boxes", json={"id": "BOX-07", "location": "Regal 3"})
    client.post("/api/v1/inventory/items", json={"name": "HDMI-Adapter", "box_id": "BOX-07"})
    loan = client.post("/api/v1/inventory/loans", json={"item": "Akkuschrauber", "person": "Kollege"}).json()

    for body in (
        {"type": "box", "box_id": "BOX-07"},
        {"type": "content", "box_id": "BOX-07"},
        {"type": "loan", "loan_id": loan["id"]},
    ):
        r = client.post("/api/v1/inventory/labels/render", json=body)
        assert r.status_code == 200, r.text
        rendered = r.json()
        assert rendered["ok"] is True
        assert rendered["preview"] is not None

    r = client.post("/api/v1/inventory/labels/print", json={"type": "content", "box_id": "BOX-07"})
    assert r.status_code == 200, r.text
    outcome = r.json()
    assert outcome["status"] == "ok"

    r = client.get(f"/api/v1/history/{outcome['history_id']}")
    assert r.status_code == 200
    assert r.json()["title"] == "Inhalt BOX-07"


def test_labels_render_unknown_box_is_404(api):
    client, _ctx = api
    r = client.post("/api/v1/inventory/labels/render", json={"type": "box", "box_id": "NOPE"})
    assert r.status_code == 404
