"""Router /homelab/ka."""

import copy

import pytest

from homelab_fakes import mock_transport, router_client, token_file, write_homelab
from tapesmith.integrations import settings
from tapesmith.webapi import routes_kleinanzeigen
from webapi_fakes import close_ctx


@pytest.fixture
def api(tmp_path):
    client, ctx = router_client(tmp_path, routes_kleinanzeigen.router)
    yield client, ctx
    close_ctx(ctx)


def test_create_and_list(api):
    client, _ctx = api
    response = client.post("/api/v1/homelab/ka", json={"titel": "Monitorarm", "preis": "25 €",
                                                        "anzeige": "https://example.org/a/1"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == "KA-001"
    assert body["status"] == "verfügbar"

    listed = client.get("/api/v1/homelab/ka").json()
    assert listed["items"][0]["id"] == "KA-001"
    assert listed["next"] == "KA-002"
    assert listed["shortlink"] is False


def test_list_filters_by_status_and_query(api):
    client, _ctx = api
    client.post("/api/v1/homelab/ka", json={"titel": "Monitorarm"})
    second = client.post("/api/v1/homelab/ka", json={"titel": "Stuhl"}).json()
    client.post(f"/api/v1/homelab/ka/{second['id']}/status",
               json={"status": "reserviert", "name": "Hubert", "datum": "2026-09-30"})

    reserved = client.get("/api/v1/homelab/ka", params={"status": "reserviert"}).json()
    assert [i["id"] for i in reserved["items"]] == [second["id"]]

    found = client.get("/api/v1/homelab/ka", params={"query": "stuhl"}).json()
    assert [i["id"] for i in found["items"]] == [second["id"]]


def test_status_reservieren_mit_datum(api):
    client, _ctx = api
    art = client.post("/api/v1/homelab/ka", json={"titel": "Monitorarm"}).json()

    response = client.post(f"/api/v1/homelab/ka/{art['id']}/status",
                           json={"status": "reserviert", "name": "Hubert", "datum": "2026-09-30"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "reserviert"
    assert body["name"] == "Hubert"
    assert body["datum"] == "30.09.2026"


def test_label_reserviert(api):
    client, _ctx = api
    art = client.post("/api/v1/homelab/ka", json={"titel": "Monitorarm"}).json()
    client.post(f"/api/v1/homelab/ka/{art['id']}/status",
               json={"status": "reserviert", "name": "Hubert", "datum": "2026-09-30"})

    response = client.get(f"/api/v1/homelab/ka/{art['id']}/label", params={"art": "reserviert"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["template"] == "reserviert"
    assert body["values"] == {"name": "Hubert", "bis": "30.09.2026"}
    assert body["warnings"] == []


def test_label_artikel_ohne_anzeige_und_ohne_dienst_ist_422(api):
    client, _ctx = api
    art = client.post("/api/v1/homelab/ka", json={"titel": "Monitorarm"}).json()

    response = client.get(f"/api/v1/homelab/ka/{art['id']}/label")
    assert response.status_code == 422
    assert "Anzeigen-Adresse" in response.json()["error"]["message"]


def test_falscher_uebergang_ist_422(api):
    client, _ctx = api
    art = client.post("/api/v1/homelab/ka", json={"titel": "Monitorarm"}).json()

    response = client.post(f"/api/v1/homelab/ka/{art['id']}/status", json={"status": "verfügbar"})
    assert response.status_code == 422


def test_unbekannte_id_ist_404(api):
    client, _ctx = api
    response = client.get("/api/v1/homelab/ka/KA-999/label")
    assert response.status_code == 404

    response = client.post("/api/v1/homelab/ka/KA-999/status", json={"status": "verkauft", "name": "x"})
    assert response.status_code == 404

    response = client.put("/api/v1/homelab/ka/KA-999", json={"titel": "x"})
    assert response.status_code == 404


def test_verkauft_ohne_datum_nutzt_ctx_now(tmp_path):
    def fixed_now():
        import datetime

        return datetime.datetime(2026, 9, 28, 12, 0, 0)

    client, ctx = router_client(tmp_path, routes_kleinanzeigen.router, now=fixed_now)
    try:
        art = client.post("/api/v1/homelab/ka", json={"titel": "Monitorarm"}).json()
        response = client.post(f"/api/v1/homelab/ka/{art['id']}/status",
                               json={"status": "verkauft", "name": "Hubert"})
        assert response.status_code == 200, response.text
        assert response.json()["datum"] == "28.09.2026"
    finally:
        close_ctx(ctx)


def test_put_aendert_anzeige_und_zieht_kurzlink_nach(tmp_path):
    data = settings.DEFAULTS | {"shortlink": {**settings.DEFAULTS["shortlink"],
                                              "base_url": "https://l.example.com",
                                              "admin_url": "https://l.example.com",
                                              "token_ref": token_file(tmp_path, "shortlink")}}
    write_homelab(data)
    calls = []
    transport = mock_transport({"PUT /api/links/KA-001": (200, {
        "id": "KA-001", "target": "https://example.org/neu", "note": "Monitorarm",
        "created": "", "updated": "", "hits": 0})}, calls=calls)
    client, ctx = router_client(tmp_path, routes_kleinanzeigen.router,
                                extras={"transports": {"shortlink": transport}})
    try:
        art = client.post("/api/v1/homelab/ka", json={"titel": "Monitorarm"}).json()
        calls.clear()
        response = client.put(f"/api/v1/homelab/ka/{art['id']}", json={"anzeige": "https://example.org/neu"})
        assert response.status_code == 200, response.text
        assert response.json()["anzeige"] == "https://example.org/neu"
        assert calls and calls[0].method == "PUT"
    finally:
        close_ctx(ctx)


def _stateful_api(tmp_path):
    from homelab_fakes import FakeShortlinkService

    service = FakeShortlinkService()
    data = copy.deepcopy(settings.DEFAULTS)
    data["shortlink"].update({"base_url": "https://l.example.com", "token_ref": token_file(tmp_path, "sl")})
    write_homelab(data)
    client, ctx = router_client(tmp_path, routes_kleinanzeigen.router,
                                extras={"transports": {"shortlink": service.transport}})
    return client, ctx, service


def test_create_legt_kurzlink_an_und_label_get_ist_ohne_netz(tmp_path):
    client, ctx, service = _stateful_api(tmp_path)
    try:
        art = client.post("/api/v1/homelab/ka", json={"titel": "Monitorarm"}).json()
        assert art["warnings"] == []
        assert service.links[art["id"]]["target"] is None
        service.links[art["id"]]["target"] = "https://anzeige.example/1"
        service.calls.clear()
        body = client.get(f"/api/v1/homelab/ka/{art['id']}/label").json()
        assert body["values"]["link"] == f"HTTPS://L.EXAMPLE.COM/{art['id']}"
        assert service.calls == []
        assert service.links[art["id"]]["target"] == "https://anzeige.example/1"
    finally:
        close_ctx(ctx)
