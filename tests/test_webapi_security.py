"""Sicherheitsschicht (Host, Origin, Sec-Fetch-Site, Token) und statische Auslieferung."""

import pytest

from webapi_fakes import BASE_URL, TOKEN, close_ctx, make_client


@pytest.fixture
def client(tmp_path):
    client, ctx = make_client(tmp_path)
    yield client
    close_ctx(ctx)


def _anon(client):
    """Gleicher Client, aber ohne Token-Header."""
    client.headers.pop("X-P12-Token", None)
    return client


def test_foreign_host_forbidden(client):
    r = client.get("/api/v1/app", headers={"Host": "evil.example:8712"})
    assert r.status_code == 403
    assert r.json()["error"]["kind"] == "Forbidden"
    assert r.json()["error"]["hint"] == "" and r.json()["error"]["exit_code"] == 1


def test_localhost_host_ok_and_wrong_port_forbidden(client):
    assert client.get("/api/v1/app", headers={"Host": "localhost:8712"}).status_code == 200
    assert client.get("/api/v1/app", headers={"Host": "127.0.0.1:9999"}).status_code == 403
    assert client.get("/health", headers={"Host": "evil.example:8712"}).status_code == 403
    assert client.get("/", headers={"Host": "evil.example:8712"}).status_code == 403


def test_origin_check(client):
    r = client.post("/api/v1/print/continue", json={}, headers={"Origin": "http://evil.example"})
    assert r.status_code == 403 and r.json()["error"]["kind"] == "Forbidden"
    r = client.post("/api/v1/print/continue", json={}, headers={"Origin": "http://127.0.0.1:8712"})
    assert r.status_code == 200
    r = client.post("/api/v1/print/continue", json={}, headers={"Origin": "http://localhost:8712"})
    assert r.status_code == 200
    r = client.post("/api/v1/print/continue", json={}, headers={"Origin": "http://127.0.0.1:9999"})
    assert r.status_code == 403


def test_sec_fetch_site_cross_site(client):
    r = client.get("/api/v1/app", headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403
    r = client.get("/", headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403
    assert client.get("/api/v1/app", headers={"Sec-Fetch-Site": "same-origin"}).status_code == 200


def test_token_required(client):
    anon = _anon(client)
    r = anon.get("/api/v1/app")
    assert r.status_code == 401 and r.json()["error"]["kind"] == "Unauthorized"
    assert anon.get("/api/v1/app", headers={"X-P12-Token": "falsch"}).status_code == 401
    assert anon.get(f"/api/v1/app?t={TOKEN}").status_code == 200
    assert anon.post(f"/api/v1/print/continue?t={TOKEN}", json={}).status_code == 401
    assert anon.get("/api/v1/app?t=falsch").status_code == 401
    assert anon.get("/api/v1/openapi.json").status_code == 401
    assert anon.get(f"/api/v1/openapi.json?t={TOKEN}").status_code == 200
    assert anon.get("/api/v1/gibtsnicht").status_code == 401


def test_health_and_index_without_token(client):
    anon = _anon(client)
    r = anon.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"ok", "app", "version", "home_key", "pid"}
    assert body["ok"] is True and body["app"] == "tapesmith" and body["home_key"] == "test-home"
    r = anon.get("/")
    assert r.status_code == 200
    assert TOKEN not in r.text
    assert "<title>P12</title>" in r.text


def test_security_headers(client):
    r = client.get("/api/v1/app")
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert r.headers["x-frame-options"] == "DENY"
    assert "access-control-allow-origin" not in r.headers
    assert client.get("/health").headers["cache-control"] == "no-store"
    assert _anon(client).get("/api/v1/app").headers["cache-control"] == "no-store"


def test_static_files(client):
    r = client.get("/assets/app.js")
    assert r.status_code == 200
    assert "immutable" in r.headers["cache-control"]
    assert "max-age=31536000" in r.headers["cache-control"]
    r = client.get("/einstellungen")
    assert r.status_code == 200 and "<title>P12</title>" in r.text
    assert r.headers["cache-control"] == "no-store"
    assert client.get("/fehlt.css").status_code == 404


def test_unknown_api_is_json_404(client):
    r = client.get("/api/v1/gibtsnicht")
    assert r.status_code == 404
    assert r.json()["error"]["kind"] == "NotFound"


@pytest.mark.parametrize("path", ["/../../etc/passwd", "/%2e%2e/secret.txt", "/assets/..%2f..%2fsecret.txt",
                                  "/..%5csecret.txt", "/assets/%2e%2e/%2e%2e/secret.txt"])
def test_no_path_traversal(tmp_path, path):
    client, ctx = make_client(tmp_path)
    try:
        (ctx.static_dir.parent / "secret.txt").write_text("GEHEIM", encoding="utf-8")
        r = client.get(path)
        assert "GEHEIM" not in r.text
    finally:
        close_ctx(ctx)


def test_missing_index_shows_build_hint(tmp_path):
    empty = tmp_path / "leer"
    empty.mkdir()
    client, ctx = make_client(tmp_path, static_dir=empty)
    try:
        r = client.get("/schnelldruck")
        assert r.status_code == 200
        assert "Oberfläche nicht gebaut" in r.text and "tools/build_web.py" in r.text
    finally:
        close_ctx(ctx)


def test_base_url_constant():
    assert BASE_URL == "http://127.0.0.1:8712"
