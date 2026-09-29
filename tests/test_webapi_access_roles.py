"""Rollen-Tabelle, LanPolicy und Hilfsfunktionen aus `webapi.access`."""

import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient

from tapesmith.webapi import access
from tapesmith.webapi.access import LanPolicy, Principal, allowed, is_loopback
from tapesmith.webapi.errors import install_handlers


@pytest.mark.parametrize("role, method, path, expected", [
    ("familie", "POST", "/api/v1/familie/drucken", True),
    ("familie", "GET", "/api/v1/status", False),
    ("drucken", "POST", "/api/v1/labels/print", True),
    ("drucken", "PATCH", "/api/v1/settings", False),
    ("drucken", "POST", "/api/v1/access/tokens", False),
    ("drucken", "POST", "/mcp", True),
    ("drucken", "GET", "/api/v1/templates/lint", True),
    ("drucken", "DELETE", "/api/v1/templates/x", False),
    ("admin", "DELETE", "/api/v1/whatever", True),
    ("gast", "GET", "/api/v1/app", False),
])
def test_allowed_examples(role, method, path, expected):
    assert allowed(role, method, path) is expected


# Kurzrouten und Familie: (Methode, Beispielpfad)
SHORT_ROUTES = [
    ("POST", "/api/v1/print"),
    ("POST", "/api/v1/print/text"),
    ("GET", "/api/v1/preview.png"),
    ("GET", "/api/v1/jobs"),
    ("DELETE", "/api/v1/jobs/17"),
    ("GET", "/api/v1/docs"),
]
FAMILY_ROUTES = [
    ("GET", "/api/v1/familie/vorlagen"),
    ("POST", "/api/v1/familie/vorschau"),
    ("POST", "/api/v1/familie/drucken"),
    ("GET", "/api/v1/familie/status"),
]


@pytest.mark.parametrize("method, path", FAMILY_ROUTES)
def test_family_routes_for_all_roles(method, path):
    for role in ("admin", "drucken", "familie"):
        assert allowed(role, method, path), (role, method, path)
    assert not allowed("gast", method, path)


@pytest.mark.parametrize("method, path", SHORT_ROUTES)
def test_short_routes_for_print_role_only(method, path):
    assert allowed("admin", method, path)
    assert allowed("drucken", method, path)
    assert not allowed("familie", method, path)


def test_access_routes_admin_only():
    for method, path in [("GET", "/api/v1/access"), ("PATCH", "/api/v1/access/settings"),
                         ("POST", "/api/v1/access/tokens"), ("DELETE", "/api/v1/access/tokens/abcd1234"),
                         ("PUT", "/api/v1/access/secrets/mqtt"), ("POST", "/api/v1/access/telegram/test")]:
        assert allowed("admin", method, path)
        assert not allowed("drucken", method, path)
        assert not allowed("familie", method, path)


def test_print_table_details():
    assert allowed("drucken", "get", "/api/v1/status")          # Methode ohne Groß-/Kleinschreibung
    assert allowed("drucken", "GET", "/api/v1/history/12/thumb.png")
    assert not allowed("drucken", "DELETE", "/api/v1/history/12")
    assert allowed("drucken", "GET", "/api/v1/gallery/abc/def")
    assert allowed("drucken", "POST", "/api/v1/batch/print")
    assert not allowed("drucken", "POST", "/api/v1/batch/contact-sheet")
    assert allowed("drucken", "DELETE", "/mcp/x")
    assert not allowed("drucken", "GET", "/api/v1/statusx")
    assert not allowed("drucken", "DELETE", "/api/v1/jobs/abc")
    assert not allowed("familie", "POST", "/mcp")


def test_lan_policy_from_config():
    cfg = {"lan": {"enabled": True, "hostnames": ["P12.lan"], "allowed_networks": ["192.0.2.0/24"]}}
    policy = LanPolicy.from_config(cfg, addresses=["192.0.2.50", "10.0.0.5"], hostname="P12PC")
    assert policy.enabled is True
    assert policy.networks == ("192.0.2.0/24",)
    assert "p12.lan" in policy.hosts
    assert "192.0.2.50" in policy.hosts
    assert "10.0.0.5" not in policy.hosts
    assert {"p12pc", "p12pc.local"} <= policy.hosts


def test_lan_policy_bind_and_defaults():
    policy = LanPolicy.from_config({"lan": {"bind": "192.0.2.9"}}, addresses=["192.0.2.50"],
                                   hostname="pc")
    assert policy.enabled is False
    assert "192.0.2.9" in policy.hosts and "192.0.2.50" not in policy.hosts
    disabled = LanPolicy.disabled()
    assert disabled.enabled is False and disabled.networks == () and disabled.hosts == frozenset()


@pytest.mark.parametrize("host, expected", [
    ("127.0.0.1", True), ("127.5.6.7", True), ("::1", True), ("192.0.2.77", False),
    (None, False), ("", False), ("testclient", False),
])
def test_is_loopback(host, expected):
    assert is_loopback(host) is expected


def _app(principal: Principal | None):
    app = FastAPI()
    install_handlers(app)

    @app.middleware("http")
    async def put(request, call_next):
        if principal is not None:
            request.scope.setdefault("state", {})["p12_principal"] = principal
        return await call_next(request)

    @app.get("/who")
    def who(request: Request):
        p = access.principal(request)
        return {"kind": p.kind, "role": p.role, "origin": access.job_origin(request)}

    @app.get("/admin", dependencies=[Depends(access.require_role("admin"))])
    def admin_only():
        return {"ok": True}

    return TestClient(app, client=("127.0.0.1", 1))


def test_principal_missing_defaults():
    client = _app(None)
    assert client.get("/who").json() == {"kind": "none", "role": None, "origin": "gui"}
    r = client.get("/admin")
    assert r.status_code == 403
    assert r.json()["error"]["message"] == "Keine Berechtigung für diese Aktion"


def test_require_role_and_origin():
    token = Principal("token", "drucken", "192.0.2.77", False, token_id="abcd1234", token_name="x",
                      origin="api")
    client = _app(token)
    assert client.get("/who").json() == {"kind": "token", "role": "drucken", "origin": "api"}
    assert client.get("/admin").status_code == 403
    session = Principal("session", "admin", "127.0.0.1", True)
    assert _app(session).get("/admin").json() == {"ok": True}
