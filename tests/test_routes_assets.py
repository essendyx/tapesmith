"""Router /homelab/assets (Client des Kurz-Link-Dienstes)."""

import json

import pytest

from homelab_fakes import FakeKeyring, mock_transport, missing_refs, router_client, token_file, write_homelab
from tapesmith.webapi import routes_assets
from webapi_fakes import close_ctx


def _shortlink_response(link_id, target=None):
    return {"id": link_id, "target": target, "note": "", "created": "2026-09-28T10:00:00",
            "updated": "2026-09-28T10:00:00", "hits": 0}


@pytest.fixture
def api(tmp_path):
    data = missing_refs(tmp_path)
    write_homelab(data)
    client, ctx = router_client(tmp_path, routes_assets.router, extras={"keyring_module": FakeKeyring()})
    yield client, ctx
    close_ctx(ctx)


@pytest.fixture
def api_with_shortlink(tmp_path):
    calls = []
    data = missing_refs(tmp_path)
    data["shortlink"] = {"base_url": "https://l.example.com", "token_ref": token_file(tmp_path, "sl")}
    write_homelab(data)
    routes = {}
    client, ctx = router_client(tmp_path, routes_assets.router,
                                extras={"keyring_module": FakeKeyring(),
                                        "transports": {"shortlink": mock_transport(routes, calls=calls)}})
    yield client, ctx, routes, calls
    close_ctx(ctx)


def test_list_shows_next_number_without_reserving(api):
    client, _ctx = api
    response = client.get("/api/v1/homelab/assets")
    assert response.status_code == 200
    body = response.json()
    assert body["assets"] == []
    assert body["range"] == {"prefix": "HL-", "width": 4, "next": "HL-0001", "check_digit": False}
    assert body["shortlink"] is False


def test_create_two_assets_advances_next(api):
    client, _ctx = api
    response = client.post("/api/v1/homelab/assets", json={"count": 2, "bezeichnung": "Patchkabel"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert [a["id"] for a in body["assets"]] == ["HL-0001", "HL-0002"]
    assert body["assets"][0]["bezeichnung"] == "Patchkabel"
    assert body["assets"][0]["status"] == "aktiv"
    assert body["warnings"] == []

    listed = client.get("/api/v1/homelab/assets").json()
    assert listed["range"]["next"] == "HL-0003"
    assert len(listed["assets"]) == 2


def test_import_existing_number(api):
    client, _ctx = api
    response = client.post("/api/v1/homelab/assets/import", json={"id": "HL-0500", "bezeichnung": "Alt-Gerät"})
    assert response.status_code == 200, response.text
    assert response.json()["id"] == "HL-0500"

    duplicate = client.post("/api/v1/homelab/assets/import", json={"id": "HL-0500"})
    assert duplicate.status_code == 422


def test_put_changes_ziel_and_upserts_shortlink(api_with_shortlink):
    client, _ctx, routes, calls = api_with_shortlink
    routes["PUT /api/links/HL-0001"] = lambda req: __import__("httpx").Response(
        201, json=_shortlink_response("HL-0001", json.loads(req.content)["target"]))
    created = client.post("/api/v1/homelab/assets", json={"count": 1}).json()["assets"][0]
    calls.clear()

    response = client.put(f"/api/v1/homelab/assets/{created['id']}", json={"ziel": "https://x.example/a"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ziel"] == "https://x.example/a"
    assert body["warnings"] == []
    assert len(calls) == 1
    assert json.loads(calls[0].content)["target"] == "https://x.example/a"


def test_put_without_shortlink_service_no_upsert(api):
    client, _ctx = api
    created = client.post("/api/v1/homelab/assets", json={"count": 1}).json()["assets"][0]
    response = client.put(f"/api/v1/homelab/assets/{created['id']}", json={"standort": "Schrank 3"})
    assert response.status_code == 200, response.text
    assert response.json()["standort"] == "Schrank 3"


def test_put_unknown_id_is_404(api):
    client, _ctx = api
    response = client.put("/api/v1/homelab/assets/HL-9999", json={"standort": "x"})
    assert response.status_code == 404


def test_void_sets_status(api):
    client, _ctx = api
    created = client.post("/api/v1/homelab/assets", json={"count": 1}).json()["assets"][0]
    response = client.post(f"/api/v1/homelab/assets/{created['id']}/void", json={"reason": "Fehldruck"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "verworfen"
    assert "Fehldruck" in body["notiz"]


def test_void_unknown_id_is_404(api):
    client, _ctx = api
    response = client.post("/api/v1/homelab/assets/HL-9999/void", json={"reason": "x"})
    assert response.status_code == 404


def test_label_without_shortlink_service_and_ziel_returns_warning(api):
    client, _ctx = api
    created = client.post("/api/v1/homelab/assets",
                          json={"count": 1, "bezeichnung": "Patchkabel", "ziel": "https://x.example/a"}
                          ).json()["assets"][0]
    response = client.get(f"/api/v1/homelab/assets/{created['id']}/label")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["template"] == "asset-kurz"
    assert body["values"] == {"nummer": "HL-0001", "bezeichnung": "Patchkabel", "link": "https://x.example/a"}
    assert body["warnings"] == ["Kurz-Link-Dienst nicht eingerichtet, QR enthält die lange Adresse"]


def test_label_with_shortlink_service(api_with_shortlink):
    client, _ctx, routes, calls = api_with_shortlink
    routes["GET /api/links/HL-0001"] = (404, {"error": "x"})
    routes["PUT /api/links/HL-0001"] = (201, _shortlink_response("HL-0001", None))
    created = client.post("/api/v1/homelab/assets", json={"count": 1, "bezeichnung": "Patchkabel"}
                          ).json()["assets"][0]
    calls.clear()
    response = client.get(f"/api/v1/homelab/assets/{created['id']}/label")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["values"]["link"] == "HTTPS://L.EXAMPLE.COM/HL-0001"
    assert body["warnings"] == []
    assert calls == []


def _stateful_api(tmp_path, token=True):
    from homelab_fakes import FakeShortlinkService

    service = FakeShortlinkService()
    data = missing_refs(tmp_path)
    ref = token_file(tmp_path, "sl") if token else f"file:{tmp_path / 'fehlt'}"
    data["shortlink"] = {"base_url": "https://l.example.com", "token_ref": ref}
    write_homelab(data)
    client, ctx = router_client(tmp_path, routes_assets.router,
                                extras={"keyring_module": FakeKeyring(),
                                        "transports": {"shortlink": service.transport}})
    return client, ctx, service


def test_label_get_keeps_target_set_elsewhere(tmp_path):
    client, ctx, service = _stateful_api(tmp_path)
    try:
        created = client.post("/api/v1/homelab/assets", json={"count": 1, "bezeichnung": "NAS"}).json()
        assert created["warnings"] == []
        assert service.links["HL-0001"]["target"] is None
        service.links["HL-0001"]["target"] = "https://ziel.example"
        service.calls.clear()
        body = client.get("/api/v1/homelab/assets/HL-0001/label").json()
        assert body["values"]["link"] == "HTTPS://L.EXAMPLE.COM/HL-0001"
        assert service.calls == []
        assert service.links["HL-0001"]["target"] == "https://ziel.example"
    finally:
        close_ctx(ctx)


def test_create_with_unreachable_shortlink_warns_but_keeps_asset(tmp_path):
    client, ctx, service = _stateful_api(tmp_path, token=False)
    try:
        response = client.post("/api/v1/homelab/assets", json={"count": 1})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["assets"][0]["id"] == "HL-0001"
        assert len(body["warnings"]) == 1
        assert "Kurz-Link" in body["warnings"][0]
        label = client.get("/api/v1/homelab/assets/HL-0001/label")
        assert label.status_code == 200, label.text
        assert service.calls == []
    finally:
        close_ctx(ctx)


def test_import_creates_missing_shortlink(tmp_path):
    client, ctx, service = _stateful_api(tmp_path)
    try:
        response = client.post("/api/v1/homelab/assets/import", json={"id": "HL-0500", "bezeichnung": "Alt"})
        assert response.status_code == 200, response.text
        assert response.json()["warnings"] == []
        assert service.links["HL-0500"]["note"] == "Alt"
    finally:
        close_ctx(ctx)


def test_label_unknown_id_is_404(api):
    client, _ctx = api
    assert client.get("/api/v1/homelab/assets/HL-9999/label").status_code == 404


def test_table_returns_pending_id_with_headers(api):
    client, _ctx = api
    created = client.post("/api/v1/homelab/assets", json={"count": 2, "bezeichnung": "Patchkabel",
                                                          "ziel": "https://x.example/a"}).json()["assets"]
    ids = [a["id"] for a in created]
    response = client.post("/api/v1/homelab/assets/table", json={"ids": ids})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["template"] == "asset-kurz"
    assert body["count"] == 2
    assert isinstance(body["pending_id"], str) and body["pending_id"]


def test_table_unknown_id_is_404(api):
    client, _ctx = api
    response = client.post("/api/v1/homelab/assets/table", json={"ids": ["HL-9999"]})
    assert response.status_code == 404


def test_export_csv_content_type(api):
    client, _ctx = api
    client.post("/api/v1/homelab/assets", json={"count": 1, "bezeichnung": "Patchkabel"})
    response = client.get("/api/v1/homelab/assets/export.csv")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert response.text.startswith("﻿id;bezeichnung;")
    assert "HL-0001;Patchkabel" in response.text
