"""Router /homelab/proxmox (hosts, guests, table). Nur MockTransport und Fake-Keyring."""

import httpx
import pytest

from homelab_fakes import FakeKeyring, load_json, missing_refs, mock_transport, router_client, token_file, write_homelab
from tapesmith.webapi import batchapi, routes_proxmox
from test_proxmox import TOKEN, _routes
from webapi_fakes import close_ctx

# Integrationen im Produkt ohne Standardadressen: Tests nutzen neutrale Testadressen.
pytestmark = pytest.mark.usefixtures("homelab_test_defaults")


def _homelab(tmp_path, *, token: bool = True, shortlink: bool = False) -> dict:
    data = missing_refs(tmp_path)
    ref = token_file(tmp_path, "pve", TOKEN) if token else f"file:{tmp_path / 'no-tokens' / 'pve'}"
    data["proxmox"] = {"hosts": [{"name": "pmx10", "url": "https://192.0.2.60:8006", "token_ref": ref}]}
    if shortlink:
        data["shortlink"] = {"base_url": "https://l.example.com", "token_ref": token_file(tmp_path, "sl")}
    write_homelab(data)
    return data


@pytest.fixture
def make_api(tmp_path):
    made = []

    def factory(*, token=True, shortlink=False, pve_routes=None, sl_routes=None, calls=None):
        _homelab(tmp_path, token=token, shortlink=shortlink)
        transports = {"proxmox": mock_transport(pve_routes or _routes(), calls=calls),
                      "shortlink": mock_transport(sl_routes or {}, calls=calls)}
        client, ctx = router_client(tmp_path, routes_proxmox.router,
                                    extras={"keyring_module": FakeKeyring(), "transports": transports})
        made.append(ctx)
        return client, ctx

    yield factory
    for ctx in made:
        close_ctx(ctx)


def test_hosts_without_token(make_api):
    client, _ctx = make_api(token=False)
    response = client.get("/api/v1/homelab/proxmox/hosts")
    assert response.status_code == 200
    host = response.json()["hosts"][0]
    assert host["name"] == "pmx10" and host["url"] == "https://192.0.2.60:8006"
    assert host["verify_tls"] is False
    assert host["token_set"] is False
    assert host["token_describe"].startswith("Datei ")


def test_hosts_with_token(make_api):
    client, _ctx = make_api()
    assert client.get("/api/v1/homelab/proxmox/hosts").json()["hosts"][0]["token_set"] is True


def test_guests_with_filter(make_api):
    client, _ctx = make_api()
    response = client.post("/api/v1/homelab/proxmox/guests", json={"host": "pmx10", "status": "running"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["host"] == "pmx10"
    assert body["nodes"] == [{"host": "pmx10", "node": "pmx10", "status": "online", "ip": "192.0.2.60"}]
    assert [g["vmid"] for g in body["guests"]] == [102, 103, 111]
    vm = body["guests"][2]
    assert vm["ips"] == ["192.0.2.39"] and vm["ip_kurz"] == ".39"
    assert vm["tags"] == ["ai", "gpu"]
    assert vm["passthrough"] == ["hostpci0: 0000:01:00.0,pcie=1", "usb0: host=1-2"]
    assert set(vm) >= {"host", "node", "vmid", "kind", "name", "status", "tags", "ips", "ip_note",
                       "passthrough", "ip_kurz"}
    assert body["warnings"] == ["TLS-Zertifikat von pmx10 wird nicht geprüft"]


def test_guests_kind_and_ids(make_api):
    client, _ctx = make_api()
    body = client.post("/api/v1/homelab/proxmox/guests",
                       json={"host": "pmx10", "kind": "lxc", "ids": "100-110", "name": "FRI"}).json()
    assert [g["vmid"] for g in body["guests"]] == [102]


def test_guests_stopped_note(make_api):
    client, _ctx = make_api()
    body = client.post("/api/v1/homelab/proxmox/guests", json={"host": "pmx10", "status": "stopped"}).json()
    assert body["guests"][0]["ip_note"] == "IP unbekannt: gestoppt"


def test_guests_unknown_host_422(make_api):
    client, _ctx = make_api()
    response = client.post("/api/v1/homelab/proxmox/guests", json={"host": "pmx30"})
    assert response.status_code == 422
    assert "pmx30" in response.json()["error"]["message"]


def test_guests_token_missing_424(make_api):
    client, _ctx = make_api(token=False)
    response = client.post("/api/v1/homelab/proxmox/guests", json={"host": "pmx10"})
    assert response.status_code == 424
    assert "Token fehlt: Proxmox pmx10" in response.json()["error"]["message"]


def test_table_with_shortlink(make_api):
    calls: list[httpx.Request] = []

    def put(request):
        return httpx.Response(200, json={"id": "PMX10-111", "target": "x", "note": "", "created": "",
                                         "updated": "", "hits": 0})

    client, ctx = make_api(shortlink=True, sl_routes={"PUT /api/links/PMX10-111": put}, calls=calls)
    response = client.post("/api/v1/homelab/proxmox/table", json={"host": "pmx10", "vmids": [111], "links": True})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["template"] == "vm-lxc-qr" and body["count"] == 1
    table = batchapi.load_source(ctx, {"type": "pending", "id": body["pending_id"]})
    assert table.headers == ("typ", "vmid", "name", "ip_kurz", "ip", "node", "host", "link")
    row = dict(zip(table.headers, table.rows[0]))
    assert row["link"] == "HTTPS://L.EXAMPLE.COM/PMX10-111"
    assert row["vmid"] == "111" and row["ip_kurz"] == ".39"
    assert [c.method for c in calls if "/api2/" in c.url.path] == ["GET"] * len(
        [c for c in calls if "/api2/" in c.url.path])
    assert not any("Kurz-Link" in w for w in body["warnings"])


def test_table_without_shortlink_uses_console_url(make_api):
    client, ctx = make_api()
    body = client.post("/api/v1/homelab/proxmox/table",
                       json={"host": "pmx10", "vmids": [111, 102], "links": True}).json()
    assert body["template"] == "vm-lxc-qr" and body["count"] == 2
    assert "Kurz-Link-Dienst nicht eingerichtet, QR enthält die lange Proxmox-Adresse" in body["warnings"]
    table = batchapi.load_source(ctx, {"type": "pending", "id": body["pending_id"]})
    links = [dict(zip(table.headers, r))["link"] for r in table.rows]
    assert "https://192.0.2.60:8006/#v1:0:=qemu%2F111" in links


def test_table_without_links(make_api):
    client, ctx = make_api()
    body = client.post("/api/v1/homelab/proxmox/table",
                       json={"host": "pmx10", "vmids": [103], "links": False}).json()
    assert body["template"] == "vm-lxc" and body["count"] == 1
    table = batchapi.load_source(ctx, {"type": "pending", "id": body["pending_id"]})
    assert table.rows[0][:4] == ("LXC", "103", "ollama", ".55")


def test_table_unknown_vmid_422(make_api):
    client, _ctx = make_api()
    response = client.post("/api/v1/homelab/proxmox/table", json={"host": "pmx10", "vmids": [999]})
    assert response.status_code == 422


def test_resources_data_is_example():
    assert len(load_json("proxmox/resources.json")["data"]) == 4
