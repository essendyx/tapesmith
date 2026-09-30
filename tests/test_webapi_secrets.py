"""Geheimwerte über die Web-API (/api/v1/secrets): setzen, übernehmen, entfernen, nie ausgeben."""

from __future__ import annotations

import json
import logging

import pytest

from tapesmith import config as config_mod
from tapesmith.integrations import settings as homelab_settings
from webapi_fakes import close_ctx, make_client, make_token

SECRETS = "/api/v1/secrets"
VALUE = "geheim-wert-4711"


class FakeKeyring:
    def __init__(self):
        self.store: dict[tuple[str, str], str] = {}

    def get_password(self, service, user):
        return self.store.get((service, user))

    def set_password(self, service, user, value):
        self.store[(service, user)] = value

    def delete_password(self, service, user):
        if (service, user) not in self.store:
            raise KeyError(user)
        del self.store[(service, user)]


@pytest.fixture
def api(tmp_path):
    keyring = FakeKeyring()
    client, ctx = make_client(tmp_path, extras={"keyring": keyring, "environ": {}})
    yield client, ctx, keyring
    close_ctx(ctx)


def _slots(client) -> dict:
    r = client.get(SECRETS)
    assert r.status_code == 200, r.text
    return {s["id"]: s for s in r.json()["slots"]}


def test_list_slots_default(api):
    client, _ctx, _kr = api
    slots = _slots(client)
    assert list(slots)[:5] == ["mqtt", "telegram", "paperless", "homeassistant", "shortlink"]
    assert slots["mqtt"]["source"] == "tapesmith" and slots["mqtt"]["set"] is False
    assert slots["telegram"]["source"] == "none"
    for slot in slots.values():
        assert set(slot) == {"id", "label", "source", "set"}


def test_store_sets_managed_ref_and_never_returns_value(api, caplog):
    client, _ctx, keyring = api
    caplog.set_level(logging.DEBUG)
    r = client.put(f"{SECRETS}/telegram", json={"value": VALUE})
    assert r.status_code == 200, r.text
    assert r.json() == {"id": "telegram", "label": "Telegram-Bot-Token", "source": "tapesmith", "set": True}
    assert keyring.store[("tapesmith", "telegram")] == VALUE
    assert config_mod.setting(config_mod.load_config(), "telegram.token_ref") == "keyring:tapesmith/telegram"
    assert VALUE not in client.get(SECRETS).text
    assert VALUE not in client.get("/api/v1/access").text
    assert VALUE not in caplog.text
    assert "telegram" in caplog.text


def test_store_homelab_slot(api):
    client, _ctx, keyring = api
    r = client.put(f"{SECRETS}/paperless", json={"value": VALUE})
    assert r.status_code == 200, r.text
    assert keyring.store[("tapesmith", "paperless")] == VALUE
    data = homelab_settings.load_settings()
    assert data["paperless"]["token_ref"] == "keyring:tapesmith/paperless"


def test_proxmox_host_slot(api):
    client, _ctx, keyring = api
    homelab_settings.update_settings({"proxmox.hosts": [{"name": "pve1", "url": "https://192.0.2.5:8006",
                                                          "token_ref": None, "verify_tls": False}]})
    slots = _slots(client)
    assert slots["proxmox:pve1"]["source"] == "none"
    r = client.put(f"{SECRETS}/proxmox:pve1", json={"value": VALUE})
    assert r.status_code == 200, r.text
    assert keyring.store[("tapesmith", "proxmox-pve1")] == VALUE
    host = homelab_settings.load_settings()["proxmox"]["hosts"][0]
    assert host["token_ref"] == "keyring:tapesmith/proxmox-pve1"
    assert host["url"] == "https://192.0.2.5:8006"


def test_adopt_external_file(api, tmp_path):
    client, _ctx, keyring = api
    token_file = tmp_path / "token.txt"
    token_file.write_text(VALUE + "\n", encoding="utf-8")
    homelab_settings.update_settings({"homeassistant.token_ref": f"file:{token_file}"})
    slots = _slots(client)
    assert slots["homeassistant"] == {"id": "homeassistant", "label": "Home Assistant", "source": "extern",
                                      "set": True}
    assert str(token_file) not in client.get(SECRETS).text
    r = client.post(f"{SECRETS}/homeassistant/adopt")
    assert r.status_code == 200, r.text
    assert r.json()["source"] == "tapesmith" and r.json()["set"] is True
    assert VALUE not in r.text
    assert keyring.store[("tapesmith", "homeassistant")] == VALUE
    assert homelab_settings.load_settings()["homeassistant"]["token_ref"] == "keyring:tapesmith/homeassistant"
    assert token_file.read_text(encoding="utf-8").strip() == VALUE


def test_adopt_env_and_missing_source(api):
    client, ctx, keyring = api
    config_mod.save_config({"telegram": {"token_ref": "env:TG_TOKEN"}})
    assert client.post(f"{SECRETS}/telegram/adopt").status_code == 422
    ctx.extras["environ"] = {"TG_TOKEN": VALUE}
    r = client.post(f"{SECRETS}/telegram/adopt")
    assert r.status_code == 200, r.text
    assert keyring.store[("tapesmith", "telegram")] == VALUE


def test_adopt_without_external_422(api):
    client, _ctx, _kr = api
    assert client.post(f"{SECRETS}/paperless/adopt").status_code == 422


def test_remove_managed_and_external(api, tmp_path):
    client, _ctx, keyring = api
    client.put(f"{SECRETS}/shortlink", json={"value": VALUE})
    r = client.delete(f"{SECRETS}/shortlink")
    assert r.status_code == 200, r.text
    assert r.json()["source"] == "none" and r.json()["set"] is False
    assert ("tapesmith", "shortlink") not in keyring.store
    assert homelab_settings.load_settings()["shortlink"]["token_ref"] is None

    token_file = tmp_path / "t.txt"
    token_file.write_text(VALUE, encoding="utf-8")
    homelab_settings.update_settings({"shortlink.token_ref": f"file:{token_file}"})
    assert client.delete(f"{SECRETS}/shortlink").json()["source"] == "none"
    assert token_file.exists()


def test_remove_mqtt_default_ref(api):
    client, _ctx, keyring = api
    client.put(f"{SECRETS}/mqtt", json={"value": VALUE})
    assert keyring.store[("tapesmith", "mqtt")] == VALUE
    r = client.delete(f"{SECRETS}/mqtt")
    assert r.status_code == 200
    assert ("tapesmith", "mqtt") not in keyring.store
    assert r.json()["set"] is False


def test_unknown_slot_and_empty_value(api):
    client, _ctx, _kr = api
    assert client.put(f"{SECRETS}/gibtsnicht", json={"value": "x"}).status_code == 404
    assert client.put(f"{SECRETS}/proxmox:fehlt", json={"value": "x"}).status_code == 404
    assert client.delete(f"{SECRETS}/gibtsnicht").status_code == 404
    assert client.put(f"{SECRETS}/telegram", json={"value": "  "}).status_code == 422


def test_other_roles_forbidden(api):
    client, ctx, _kr = api
    for role in ("drucken", "familie"):
        token = make_token(ctx, role)
        headers = {"Authorization": f"Bearer {token}"}
        assert client.get(SECRETS, headers=headers).status_code == 403
        assert client.put(f"{SECRETS}/telegram", json={"value": VALUE}, headers=headers).status_code == 403


def test_without_token_unauthorized(api):
    client, _ctx, _kr = api
    client.headers.pop("X-P12-Token", None)
    assert client.get(SECRETS).status_code == 401
    assert client.put(f"{SECRETS}/telegram", json={"value": VALUE}).status_code == 401


def test_value_not_in_config_files(api, tmp_path):
    client, _ctx, _kr = api
    for slot in ("mqtt", "telegram", "paperless", "homeassistant", "shortlink"):
        assert client.put(f"{SECRETS}/{slot}", json={"value": VALUE}).status_code == 200
    from tapesmith import paths

    for path in (paths.config_path(), homelab_settings.settings_path()):
        assert VALUE not in path.read_text(encoding="utf-8")
    assert json.loads(homelab_settings.settings_path().read_text(encoding="utf-8"))
