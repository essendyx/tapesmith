"""Module in der Web-API: `/api/v1/modules`, Schalter ohne Neustart, gesperrte Routen ausgeschalteter
Module (`module.disabled`, 409), `modules` in `/app` und ausgeblendete Modulvorlagen."""

from __future__ import annotations

import pytest

from tapesmith import modules
from webapi_fakes import close_ctx, make_client


@pytest.fixture
def api(tmp_path):
    client, ctx = make_client(tmp_path, config={"modules": {"enabled": []}})
    yield client, ctx
    close_ctx(ctx)


def _error(response) -> dict:
    return response.json()["error"]


def test_liste_mit_beschreibung_und_zustand(api):
    client, _ctx = api
    r = client.get("/api/v1/modules")
    assert r.status_code == 200
    data = r.json()
    assert [m["id"] for m in data["modules"]] == list(modules.MODULE_IDS)
    assert all(m["enabled"] is False for m in data["modules"])
    inventar = data["modules"][0]
    assert inventar["texts"]["de"]["name"] == "Inventar"
    assert inventar["pages"] == ["/inventar"]
    assert data["enabled"] == []


@pytest.mark.parametrize("method, path, module_id", [
    ("GET", "/api/v1/inventory/boxes", "inventar"),
    ("GET", "/api/v1/drives", "datentraeger"),
    ("GET", "/api/v1/ssh/hosts", "datentraeger"),
    ("POST", "/api/v1/homelab/zfs/scan", "datentraeger"),
    ("GET", "/api/v1/homelab/proxmox/hosts", "proxmox"),
    ("GET", "/api/v1/homelab/paperless/asn/next", "paperless"),
    ("GET", "/api/v1/homelab/ha/batteries", "homeassistant"),
    ("GET", "/api/v1/homelab/vault/notes", "vault"),
    ("GET", "/api/v1/homelab/assets", "assets"),
    ("GET", "/api/v1/homelab/kabel/register", "kabel"),
    ("GET", "/api/v1/homelab/ka", "kleinanzeigen"),
    ("POST", "/api/v1/homelab/codescan", "snscan"),
])
def test_ausgeschaltet_antwortet_module_disabled(api, method, path, module_id):
    client, _ctx = api
    r = client.request(method, path, json={})
    assert r.status_code == 409, r.text
    err = _error(r)
    assert err["code"] == "module.disabled"
    assert "ist ausgeschaltet" in err["message"]
    assert f"tapesmith module enable {module_id}" in err["message"]
    assert err["details"] == {"module": module_id}


def test_kern_bleibt_erreichbar(api):
    client, _ctx = api
    for path in ("/api/v1/app", "/api/v1/templates", "/api/v1/homelab/settings", "/api/v1/homelab/check",
                 "/api/v1/settings", "/api/v1/modules"):
        assert client.get(path).status_code == 200, path


def test_einschalten_wirkt_ohne_neustart(api):
    client, ctx = api
    assert client.get("/api/v1/inventory/boxes").status_code == 409
    seen = []
    ctx.broker.publish = lambda event, data: seen.append((event, data))  # type: ignore[method-assign]
    r = client.put("/api/v1/modules/inventar", json={"enabled": True})
    assert r.status_code == 200
    assert r.json()["enabled"] == ["inventar"]
    assert ("config", {"keys": ["modules.enabled"]}) in seen
    assert client.get("/api/v1/inventory/boxes").status_code == 200
    assert client.get("/api/v1/app").json()["modules"] == ["inventar"]
    r = client.put("/api/v1/modules/inventar", json={"enabled": False})
    assert r.json()["enabled"] == []
    assert client.get("/api/v1/inventory/boxes").status_code == 409


def test_unbekanntes_modul(api):
    client, _ctx = api
    r = client.put("/api/v1/modules/gibtesnicht", json={"enabled": True})
    assert r.status_code == 404
    assert _error(r)["code"] == "not_found"


def test_vault_notiz_eines_assets_braucht_beide_module(api):
    client, _ctx = api
    client.put("/api/v1/modules/assets", json={"enabled": True})
    r = client.post("/api/v1/homelab/assets/HL-0001/vault-note")
    assert r.status_code == 409
    assert _error(r)["details"] == {"module": "vault"}


def test_modulvorlagen_ausgeblendet(api):
    client, _ctx = api
    names = {t["name"] for t in client.get("/api/v1/templates").json()["templates"]}
    assert "gefriergut" in names
    assert not names & {"asn", "vm-lxc", "datentraeger", "aufbewahrungsbox", "ka-artikel"}
    gallery = client.get("/api/v1/gallery").json()
    gallery_names = {t["name"] for c in gallery["categories"] for t in c["templates"]}
    assert "Datenträger" not in {c["name"] for c in gallery["categories"]}
    assert "vm-lxc" not in gallery_names and "gefriergut" in gallery_names
    client.put("/api/v1/modules/proxmox", json={"enabled": True})
    names = {t["name"] for t in client.get("/api/v1/templates").json()["templates"]}
    assert {"vm-lxc", "vm-lxc-qr"} <= names
    assert "asn" not in names


def test_alle_module_eingeschaltet_ohne_liste(tmp_path):
    # Ohne `modules` in config.json gilt die Erkennung (in den Tests: alle eingeschaltet).
    client, ctx = make_client(tmp_path)
    try:
        assert client.get("/api/v1/app").json()["modules"] == list(modules.MODULE_IDS)
        assert client.get("/api/v1/inventory/boxes").status_code == 200
    finally:
        close_ctx(ctx)
