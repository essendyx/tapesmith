"""Router /homelab/settings und /homelab/check, API-Hilfen."""

import json

import pytest
from fastapi import APIRouter

from homelab_fakes import FakeKeyring, missing_refs, router_client, token_file, write_homelab
from tapesmith.integrations import settings
from tapesmith.integrations.errors import NotReachable
from tapesmith.webapi import batchapi, homelab_common, routes_homelab
from webapi_fakes import close_ctx


@pytest.fixture
def api(tmp_path):
    write_homelab(missing_refs(tmp_path))
    client, ctx = router_client(tmp_path, routes_homelab.router, extras={"keyring_module": FakeKeyring()})
    yield client, ctx
    close_ctx(ctx)


def test_get_settings(api):
    client, _ctx = api
    response = client.get("/api/v1/homelab/settings")
    assert response.status_code == 200
    body = response.json()
    assert body["path"] == str(settings.settings_path())
    assert body["settings"]["assets"]["prefix"] == "HL-"
    assert body["settings"]["paperless"]["token_set"] is False
    assert body["settings"]["paperless"]["token_describe"].startswith("Datei ")


def test_patch_two_valid_changes(api):
    client, _ctx = api
    response = client.patch("/api/v1/homelab/settings",
                            json={"changes": {"paperless.asn_prefix": "PL", "assets.width": 5}})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["settings"]["paperless"]["asn_prefix"] == "PL"
    assert body["settings"]["assets"]["width"] == 5
    stored = json.loads(settings.settings_path().read_text(encoding="utf-8"))
    assert stored["paperless"]["asn_prefix"] == "PL"
    assert stored["assets"] == {"width": 5}


def test_patch_publishes_event(api, monkeypatch):
    client, ctx = api
    events = []
    monkeypatch.setattr(ctx, "publish", lambda event, data: events.append((event, data)))
    assert client.patch("/api/v1/homelab/settings",
                        json={"changes": {"assets.prefix": "AS-"}}).status_code == 200
    assert events == [("homelab", {"keys": ["assets.prefix"]})]


def test_patch_valid_and_invalid_saves_nothing(api):
    client, _ctx = api
    before = settings.settings_path().read_text(encoding="utf-8")
    response = client.patch("/api/v1/homelab/settings",
                            json={"changes": {"paperless.asn_prefix": "PL", "assets.width": 99}})
    assert response.status_code == 422
    error = response.json()["error"]
    assert len(error["details"]["errors"]) == 1
    assert "assets.width" in error["details"]["errors"][0]
    assert settings.settings_path().read_text(encoding="utf-8") == before


def test_patch_rejects_token_value(api):
    client, _ctx = api
    response = client.patch("/api/v1/homelab/settings", json={"changes": {"paperless.token": "x"}})
    assert response.status_code == 422
    assert "paperless.token" in response.json()["error"]["details"]["errors"][0]


def test_patch_accepts_token_ref_and_proxmox_list(api, tmp_path):
    client, _ctx = api
    hosts = [{"name": "pmx10", "url": "https://192.0.2.60:8006",
              "token_ref": token_file(tmp_path, "pve"), "verify_tls": False}]
    response = client.patch("/api/v1/homelab/settings", json={"changes": {
        "paperless.token_ref": "keyring:tapesmith/paperless", "proxmox.hosts": hosts}})
    assert response.status_code == 200, response.text
    body = response.json()["settings"]
    assert body["paperless"]["token_describe"] == "Windows-Anmeldeinformationen tapesmith/paperless"
    assert body["proxmox"]["hosts"][0]["token_set"] is True
    assert "test-token-123" not in response.text


def test_patch_unknown_key_is_422(api):
    client, _ctx = api
    response = client.patch("/api/v1/homelab/settings", json={"changes": {"assets.foo": 1}})
    assert response.status_code == 422
    assert "unbekannter Schlüssel 'assets.foo'" in response.json()["error"]["details"]["errors"][0]


def test_check_without_tokens(api):
    client, _ctx = api
    response = client.get("/api/v1/homelab/check")
    assert response.status_code == 200
    services = {s["id"]: s for s in response.json()["services"]}
    assert set(services) == {"paperless", "proxmox", "obsidian", "homeassistant", "shortlink"}
    assert services["paperless"]["token_set"] is False
    assert services["homeassistant"]["token_set"] is False
    assert services["obsidian"]["token_set"] is None
    assert services["proxmox"]["configured"] is False
    assert services["proxmox"]["detail"] == "Keine Proxmox-Hosts eingetragen"
    assert services["shortlink"]["configured"] is False
    for service in services.values():
        assert set(service) == {"id", "label", "configured", "token_set", "detail"}


def test_check_with_token_file_and_hosts(tmp_path):
    data = missing_refs(tmp_path)
    data["paperless"]["token_ref"] = token_file(tmp_path, "paperless")
    data["proxmox"] = {"hosts": [{"name": "pmx10", "url": "https://192.0.2.60:8006",
                                  "token_ref": "keyring:tapesmith/pmx10"}]}
    data["shortlink"]["base_url"] = "https://l.example.com"
    write_homelab(data)
    client, ctx = router_client(tmp_path, routes_homelab.router, extras={
        "keyring_module": FakeKeyring({("tapesmith", "pmx10"): "k"})})
    try:
        services = {s["id"]: s for s in client.get("/api/v1/homelab/check").json()["services"]}
    finally:
        close_ctx(ctx)
    assert services["paperless"]["token_set"] is True
    assert services["proxmox:pmx10"]["configured"] is True
    assert services["proxmox:pmx10"]["token_set"] is True
    assert services["proxmox:pmx10"]["label"] == "Proxmox pmx10"
    assert "proxmox" not in services
    assert services["shortlink"]["configured"] is True


def test_broken_settings_file_is_422(tmp_path):
    settings.settings_path().write_text("{kaputt", encoding="utf-8")
    client, ctx = router_client(tmp_path, routes_homelab.router)
    try:
        response = client.get("/api/v1/homelab/settings")
    finally:
        close_ctx(ctx)
    assert response.status_code == 422
    assert "homelab.json" in response.json()["error"]["message"]


def test_install_integration_handler(tmp_path):
    router = APIRouter()

    @router.get("/boom")
    def boom():
        raise NotReachable("Paperless", "nicht erreichbar (x)", hint="Adresse und Netz prüfen")

    client, ctx = router_client(tmp_path, router)
    try:
        response = client.get("/api/v1/boom")
    finally:
        close_ctx(ctx)
    assert response.status_code == 503
    error = response.json()["error"]
    assert error["kind"] == "NotReachable"
    assert error["exit_code"] == 5
    assert error["message"] == "Paperless: nicht erreichbar (x)"
    assert error["hint"] == "Adresse und Netz prüfen"


def test_pending_table_is_loadable(tmp_path):
    client, ctx = router_client(tmp_path)
    try:
        pid = homelab_common.pending_table(ctx, ["host", "slot"], [["pmx10", "SSD-1"], ["pmx10", "SSD-2"]],
                                           "Proxmox")
        table = batchapi.load_source(ctx, {"type": "pending", "id": pid})
    finally:
        close_ctx(ctx)
    assert table.headers == ("host", "slot")
    assert table.rows == (("pmx10", "SSD-1"), ("pmx10", "SSD-2"))
    assert table.source == "Proxmox"


def test_extras_helpers(tmp_path):
    fake = FakeKeyring()
    marker = object()
    client, ctx = router_client(tmp_path, extras={"keyring_module": fake, "transports": {"paperless": marker}})
    try:
        assert homelab_common.keyring_for(ctx) is fake
        assert homelab_common.transport_for(ctx, "paperless") is marker
        assert homelab_common.transport_for(ctx, "proxmox") is None
        assert homelab_common.load_homelab(ctx) == settings.DEFAULTS
    finally:
        close_ctx(ctx)
