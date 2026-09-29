"""Zugriffs-API (Tokens, Einstellungen, Secrets, Telegram-Test)."""

from __future__ import annotations

import json

import pytest

from tapesmith import config as config_mod
from tapesmith import paths
from webapi_fakes import close_ctx, make_client, make_token

ACCESS = "/api/v1/access"


class FakeKeyring:
    def __init__(self):
        self._store: dict[tuple[str, str], str] = {}

    def get_password(self, service, user):
        return self._store.get((service, user))

    def set_password(self, service, user, value):
        self._store[(service, user)] = value


@pytest.fixture
def api(tmp_path):
    client, ctx = make_client(tmp_path, extras={"addresses": ["192.0.2.50"], "keyring": FakeKeyring()})
    yield client, ctx
    close_ctx(ctx)


# ---------- GET /access ----------

def test_get_access_defaults(api):
    client, _ctx = api
    r = client.get(ACCESS)
    assert r.status_code == 200
    body = r.json()
    for key in ("lan", "local_addresses", "tokens", "family", "mcp", "hotfolder", "mqtt", "telegram", "addons"):
        assert key in body
    assert body["lan"]["enabled"] is False
    assert body["lan"]["restart_needed"] is False
    assert body["tokens"] == []
    assert body["addons"] == []
    assert body["family"]["available"], "keine Vorlagen gefunden"
    names = [t["name"] for t in body["family"]["available"]]
    assert names == sorted(names)


def test_get_access_forbidden_for_other_roles(api):
    client, ctx = api
    print_token = make_token(ctx, "drucken")
    family_token = make_token(ctx, "familie")

    r = client.get(ACCESS, headers={"Authorization": f"Bearer {print_token}"})
    assert r.status_code == 403
    r = client.get(ACCESS, headers={"Authorization": f"Bearer {family_token}"})
    assert r.status_code == 403


# ---------- POST/DELETE /access/tokens ----------

def test_create_token_and_family_urls(api):
    client, _ctx = api
    config_mod.save_config({"lan": {"enabled": True, "allowed_networks": ["192.0.2.0/24"]}})
    r = client.post(f"{ACCESS}/tokens", json={"name": "Handy", "role": "familie"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["secret"].startswith("p12_")
    assert body["token"]["id"] in body["token"]["hint"]
    assert body["family_urls"], "keine family_urls berechnet"
    assert any(url.startswith("http://192.0.2.50") and "/familie#t=p12_" in url
              for url in body["family_urls"])

    listed = client.get(ACCESS).json()
    listing_text = json.dumps(listed)
    assert body["secret"] not in listing_text
    assert not any("secret" in t for t in listed["tokens"])
    ids = [t["id"] for t in listed["tokens"]]
    assert body["token"]["id"] in ids

    # das Token funktioniert sofort
    r2 = client.get("/api/v1/familie/status", headers={"Authorization": f"Bearer {body['secret']}"})
    assert r2.status_code != 401


def test_create_token_familie_ohne_lan_hat_leere_family_urls(api):
    """lan.enabled ist aus (Standard): ein Familienlink waere irrefuehrend, weil der Dienst dann
    aus dem Heimnetz nicht erreichbar ist."""
    client, _ctx = api
    r = client.post(f"{ACCESS}/tokens", json={"name": "Handy", "role": "familie"})
    assert r.status_code == 200, r.text
    assert r.json()["family_urls"] == []


def test_delete_token(api):
    client, ctx = api
    secret = make_token(ctx, "drucken", name="Werkstatt")
    token_id = ctx.tokens.list()[0].id

    r = client.delete(f"{ACCESS}/tokens/{token_id}")
    assert r.status_code == 200

    check = client.get(ACCESS, headers={"Authorization": f"Bearer {secret}"})
    assert check.status_code == 401

    assert client.delete(f"{ACCESS}/tokens/deadbeef").status_code == 404
    assert client.delete(f"{ACCESS}/tokens/../x").status_code == 404


# ---------- PATCH /access/settings ----------

def test_patch_settings_ok(api):
    client, ctx = api
    sub = ctx.broker.subscribe()
    r = client.patch(f"{ACCESS}/settings", json={"changes": {"lan.enabled": True, "family.max_copies": 3}})
    assert r.status_code == 200, r.text
    data = json.loads(paths.config_path().read_text(encoding="utf-8"))
    assert data["lan"]["enabled"] is True
    assert data["family"]["max_copies"] == 3
    assert r.json()["lan"]["restart_needed"] is True

    event = sub.get(1.0)
    assert event is not None
    name, payload = event
    assert name == "config"
    assert set(payload["keys"]) == {"lan.enabled", "family.max_copies"}


def test_patch_settings_invalid_value_saves_nothing(api):
    client, _ctx = api
    r = client.patch(f"{ACCESS}/settings", json={"changes": {"lan.bind": "abc", "family.max_copies": 3}})
    assert r.status_code == 422
    path = paths.config_path()
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    assert "family" not in data
    assert data.get("lan", {}).get("bind") != "abc"


def test_patch_settings_unknown_key(api):
    client, _ctx = api
    r = client.patch(f"{ACCESS}/settings", json={"changes": {"gui.ctrl_enter_only": True}})
    assert r.status_code == 422


# ---------- PUT /access/secrets ----------

def test_put_secret_mqtt(api):
    client, ctx = api
    r = client.put(f"{ACCESS}/secrets/mqtt", json={"value": "pw"})
    assert r.status_code == 200, r.text
    assert "pw" not in r.text
    assert ctx.extras["keyring"].get_password("tapesmith", "mqtt") == "pw"
    assert client.get(ACCESS).json()["mqtt"]["password_set"] is True


def test_put_secret_telegram_default_file_ref_rejected(api):
    client, _ctx = api
    r = client.put(f"{ACCESS}/secrets/telegram", json={"value": "abc"})
    assert r.status_code == 422


def test_put_secret_unknown_name_404(api):
    client, _ctx = api
    assert client.put(f"{ACCESS}/secrets/gibtsnicht", json={"value": "x"}).status_code == 404


def test_put_secret_empty_value_422(api):
    client, _ctx = api
    r = client.put(f"{ACCESS}/secrets/mqtt", json={"value": ""})
    assert r.status_code == 422


# ---------- POST /access/telegram/test ----------

def test_telegram_test_ok(api, tmp_path):
    client, ctx = api
    token_file = tmp_path / "telegram_token.txt"
    token_file.write_text("TOKEN123", encoding="utf-8")
    config_mod.save_config({"telegram": {"enabled": True, "chat_id": "123",
                                         "token_ref": f"file:{token_file}"}})

    calls: list[dict] = []

    class Resp:
        status_code = 200

        def json(self):
            return {"ok": True}

    def fake_post(url, json=None, timeout=None):
        calls.append(json)
        return Resp()

    ctx.extras["http_post"] = fake_post
    r = client.post(f"{ACCESS}/telegram/test", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["error"] is None
    assert calls, "kein Versand ausgeloest"


def test_telegram_test_without_chat_id(api):
    client, _ctx = api
    r = client.post(f"{ACCESS}/telegram/test", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["error"]


# ---------- addons ----------

def test_addons_status_from_manager(tmp_path):
    class FakeAddonManager:
        def statuses(self):
            return [{"name": "hotfolder", "running": False, "error": None, "detail": "aus"}]

    client, ctx = make_client(tmp_path, extras={"addons": FakeAddonManager()})
    body = client.get(ACCESS).json()
    assert body["addons"] == [{"name": "hotfolder", "running": False, "error": None, "detail": "aus"}]
    close_ctx(ctx)
