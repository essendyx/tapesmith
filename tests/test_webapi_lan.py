"""Sicherheitsschicht mit LAN-Freigabe, API-Tokens, Rollen und Quelle je Auftrag."""

import logging

import pytest

from daemon_fakes import FakeNow
from tapesmith.webapi.access import LanPolicy
from webapi_fakes import TOKEN, close_ctx, make_client, make_token

LAN = LanPolicy(enabled=True, networks=("192.0.2.0/24",),
                hosts=frozenset({"192.0.2.50", "p12pc", "p12pc.local"}))
LAN_IP = "192.0.2.77"
LAN_URL = "http://192.0.2.50:8712"
TEXT = {"kind": "text", "lines": ["LAN Test"]}


@pytest.fixture
def made(tmp_path):
    ctxs = []

    def factory(**kw):
        client, ctx = make_client(tmp_path, **kw)
        ctxs.append(ctx)
        return client, ctx

    yield factory
    for ctx in ctxs:
        close_ctx(ctx)


def _lan(made, *, auth=None, lan=LAN, ip=LAN_IP, **kw):
    return made(client_ip=ip, lan=lan, auth=auth, base_url=LAN_URL, **kw)


def _with_token(made, role, **kw):
    client, ctx = _lan(made, **kw)
    secret = make_token(ctx, role)
    client.headers["Authorization"] = f"Bearer {secret}"
    return client, ctx


# ---------------------------------------------------------------- Standard (Loopback) unverändert

def test_default_loopback_unchanged(made):
    client, _ctx = made()
    assert client.get("/api/v1/app").status_code == 200
    assert client.get("/api/v1/app", headers={"X-P12-Token": ""}).status_code == 401
    anon, _ = made(auth=None)
    assert anon.get("/api/v1/app").status_code == 401
    assert client.get("/api/v1/app", headers={"Host": "evil.example"}).status_code == 403
    assert client.get("/api/v1/app", headers={"Origin": "http://evil.example"}).status_code == 403
    assert client.get("/api/v1/app", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403


def test_loopback_with_api_token(made):
    client, ctx = made(auth=None)
    secret = make_token(ctx, "drucken")
    headers = {"Authorization": f"Bearer {secret}"}
    assert client.get("/api/v1/status", headers=headers).status_code == 200
    r = client.patch("/api/v1/settings", json={"changes": {}}, headers=headers)
    assert r.status_code == 403
    assert r.json()["error"]["message"] == "Keine Berechtigung für diese Aktion"


# ---------------------------------------------------------------- Netzprüfung

def test_lan_client_without_policy(made):
    client, ctx = _lan(made, lan=None)
    r = client.get("/health")
    assert r.status_code == 403
    assert r.json()["error"]["message"] == "Zugriff verweigert: Adresse nicht freigegeben"
    secret = make_token(ctx, "admin")
    assert client.get("/api/v1/app", headers={"Authorization": f"Bearer {secret}"}).status_code == 403


def test_lan_client_outside_networks(made):
    client, ctx = _lan(made, ip="10.1.1.1")
    secret = make_token(ctx, "admin")
    assert client.get("/health").status_code == 403
    assert client.get("/").status_code == 403
    assert client.get("/api/v1/app", headers={"Authorization": f"Bearer {secret}"}).status_code == 403


def test_disabled_policy_forbids_even_matching_address(made):
    off = LanPolicy(enabled=False, networks=LAN.networks, hosts=LAN.hosts)
    client, _ = _lan(made, lan=off)
    assert client.get("/health").status_code == 403


# ---------------------------------------------------------------- /health

def test_health_lan_and_loopback(made):
    client, _ = _lan(made)
    r = client.get("/health")
    assert r.status_code == 200
    assert set(r.json()) == {"ok", "app", "version"}
    local, _ = made(auth=None)
    body = local.get("/health").json()
    assert body["home_key"] == "test-home" and "pid" in body


# ---------------------------------------------------------------- Tokens und Rollen

def test_session_token_only_local(made):
    client, _ = _lan(made, auth="session")
    assert client.headers["X-P12-Token"] == TOKEN
    r = client.get("/api/v1/app")
    assert r.status_code == 401
    assert r.json()["error"]["message"] == "Nicht angemeldet: Token fehlt oder ist falsch"


def test_family_token(made):
    client, _ = _with_token(made, "familie")
    assert client.get("/api/v1/familie/vorlagen").status_code not in (401, 403)
    assert client.get("/api/v1/status").status_code == 403
    assert client.get("/api/v1/history").status_code == 403
    assert client.patch("/api/v1/settings", json={"changes": {}}).status_code == 403


def test_print_token(made):
    client, _ = _with_token(made, "drucken")
    r = client.post("/api/v1/labels/render", json={"source": TEXT})
    assert r.status_code == 200, r.text
    assert client.get("/api/v1/settings").status_code == 403


def test_admin_token(made):
    client, _ = _with_token(made, "admin")
    assert client.get("/api/v1/settings").status_code == 200


def test_bearer_scheme_case_insensitive(made):
    client, ctx = _lan(made)
    secret = make_token(ctx, "admin")
    assert client.get("/api/v1/settings", headers={"Authorization": f"bearer {secret}"}).status_code == 200


def test_x_p12_token_header_with_api_token(made):
    client, ctx = _lan(made)
    secret = make_token(ctx, "admin")
    assert client.get("/api/v1/settings", headers={"X-P12-Token": secret}).status_code == 200


def test_query_token_only_for_get(made):
    client, ctx = _lan(made)
    secret = make_token(ctx, "drucken")
    assert client.get(f"/api/v1/status?t={secret}").status_code == 200
    r = client.post(f"/api/v1/labels/render?t={secret}", json={"source": TEXT})
    assert r.status_code == 401


def test_basic_auth_ignored(made):
    client, _ = _lan(made)
    assert client.get("/api/v1/status", headers={"Authorization": "Basic xyz"}).status_code == 401


def test_revoked_token_rejected(made):
    client, ctx = _lan(made)
    secret = make_token(ctx, "admin", name="weg")
    ctx.tokens.revoke("weg")
    assert client.get("/api/v1/settings", headers={"Authorization": f"Bearer {secret}"}).status_code == 401


def test_token_never_logged(made, caplog):
    client, ctx = _lan(made)
    secret = make_token(ctx, "admin")
    caplog.set_level(logging.DEBUG)
    client.get("/api/v1/settings", headers={"Authorization": f"Bearer {secret}"})
    client.get("/api/v1/settings", headers={"Authorization": f"Bearer {secret}x"})
    assert secret not in caplog.text
    assert f"Fehlversuch von {LAN_IP}" in caplog.text


# ---------------------------------------------------------------- Host und Origin

@pytest.mark.parametrize("host, ok", [
    ("192.0.2.50:8712", True), ("p12pc.local:8712", True), ("P12PC:8712", True),
    ("attacker.example:8712", False), ("192.0.2.50:9999", False), ("192.0.2.50", False),
    ("127.0.0.1:8712", False),
])
def test_lan_host_check(made, host, ok):
    client, _ = _lan(made)
    status = client.get("/health", headers={"Host": host}).status_code
    assert (status == 200) is ok, status


def test_lan_origin_check(made):
    client, _ = _with_token(made, "admin")
    assert client.get("/api/v1/settings", headers={"Origin": LAN_URL}).status_code == 200
    assert client.get("/api/v1/settings", headers={"Origin": "http://127.0.0.1:8712"}).status_code == 403
    assert client.get("/api/v1/settings", headers={"Origin": "http://p12pc.local:8712"}).status_code == 403
    assert client.get("/api/v1/settings", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403


# ---------------------------------------------------------------- statische Dateien, /mcp

def test_static_files_for_lan_without_token(made):
    client, _ = _lan(made)
    for path in ("/", "/familie", "/assets/app.js"):
        assert client.get(path).status_code == 200, path


def test_mcp_never_serves_index(made):
    client, _ = _lan(made)
    for path in ("/mcp", "/mcp/", "/mcp/x"):
        r = client.get(path)
        assert r.status_code in (401, 404), (path, r.status_code)
        assert "<title>P12</title>" not in r.text
    local, _ = made()
    for path in ("/mcp", "/mcp/x"):
        r = local.get(path)
        assert r.status_code == 404 and "<title>P12</title>" not in r.text
        assert r.headers["cache-control"] == "no-store"


# ---------------------------------------------------------------- Quelle je Auftrag

def _printed_source(client, ctx, text, headers=None):
    r = client.post("/api/v1/labels/print", json={"source": {"kind": "text", "lines": [text]}},
                    headers=headers or {})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ok", r.json()
    return ctx.history().last().source


def test_job_origin(made):
    client, ctx = made(now=FakeNow(), auth=None)
    ctx.service._debouncer._min_interval_s = 0
    secret = make_token(ctx, "drucken")
    session = {"X-P12-Token": TOKEN}
    bearer = {"Authorization": f"Bearer {secret}"}
    assert _printed_source(client, ctx, "eins", session) == "gui"
    assert _printed_source(client, ctx, "zwei", bearer) == "api"
    assert _printed_source(client, ctx, "drei", {**session, "X-P12-Source": "mcp"}) == "mcp"
    assert _printed_source(client, ctx, "vier", {**session, "X-P12-Source": "hotkey"}) == "gui"
    assert _printed_source(client, ctx, "fuenf", {**bearer, "X-P12-Source": "gui"}) == "api"
    assert _printed_source(client, ctx, "sechs", {**bearer, "X-P12-Source": "hotfolder"}) == "hotfolder"
    assert _printed_source(client, ctx, "sieben", {**bearer, "X-P12-Source": "unbekannt"}) == "api"


def test_render_and_export_use_origin(made):
    client, ctx = made()
    r = client.post("/api/v1/labels/export", json={"source": TEXT, "format": "png"},
                    headers={"X-P12-Source": "mcp"})
    assert r.status_code == 200


def test_batch_print_origin(made):
    client, ctx = made(auth=None)
    secret = make_token(ctx, "drucken")
    definition = {"schema_version": 2, "name": "serie-quelle",
                  "fields": [{"id": "wert", "label": "Wert", "type": "input", "required": True}],
                  "layout": {"lines": ["{wert}"]}}
    r = client.post("/api/v1/templates", json={"name": "serie-quelle", "definition": definition},
                    headers={"X-P12-Token": TOKEN})
    assert r.status_code == 200, r.text
    r = client.post("/api/v1/batch/print", json={"template": "serie-quelle",
                                                 "source": {"type": "lines", "text": "a\nb"}, "options": {}},
                    headers={"Authorization": f"Bearer {secret}"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ok", r.json()
    assert ctx.history().last().source == "api"


def _family_origin_probe(client):
    """Setzt eine Probe-Route vor die (Platzhalter-)Familienrouten, die `job_origin` meldet."""
    from fastapi import Request
    from fastapi.routing import APIRoute

    from tapesmith.webapi import access

    def probe(request: Request):
        return {"origin": access.job_origin(request)}

    router = client.app.router
    router.routes.insert(0, APIRoute("/api/v1/familie/status", probe, methods=["GET"]))
    router.routes.insert(0, APIRoute("/api/v1/familie/drucken", probe, methods=["POST"]))


@pytest.mark.parametrize("role", ["familie", "drucken", "admin"])
@pytest.mark.parametrize("wanted", [None, "mcp", "api", "gui"])
def test_family_routes_always_api(made, role, wanted):
    client, _ctx = _with_token(made, role)
    _family_origin_probe(client)
    headers = {"X-P12-Source": wanted} if wanted else {}
    r = client.get("/api/v1/familie/status", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["origin"] == "api"
    r = client.post("/api/v1/familie/drucken", json={}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["origin"] == "api"


def test_family_route_session_origin_api(made):
    client, _ctx = made()
    _family_origin_probe(client)
    r = client.get("/api/v1/familie/status", headers={"X-P12-Source": "mcp"})
    assert r.status_code == 200, r.text
    assert r.json()["origin"] == "api"


def test_is_family_path():
    from tapesmith.webapi.security import is_family_path
    assert is_family_path("/api/v1/familie/status")
    assert is_family_path("/api/v1/familie")
    assert not is_family_path("/api/v1/familienname")
    assert not is_family_path("/familie")
    assert not is_family_path("/api/v1/labels/print")
