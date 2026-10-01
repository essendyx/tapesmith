"""Kern-Endpunkte, Fehlerabbildung, Akzentfarbe, kein Qt im Web-Paket."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

import tapesmith
from daemon_fakes import STATUS_QUERIES
from tapesmith.connection import PrinterOffline
from tapesmith.errors import explain
from tapesmith.lock import PrinterBusy
from tapesmith.templates.model import TemplateError
from tapesmith.transport.base import ConnectTimeout
from tapesmith.webapi import accent
from tapesmith.webapi.errors import NotFound, error_body
from webapi_fakes import close_ctx, make_client

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def api(tmp_path):
    client, ctx = make_client(tmp_path)
    yield client, ctx
    close_ctx(ctx)


def test_app_info(api):
    client, ctx = api
    r = client.get("/api/v1/app")
    assert r.status_code == 200
    body = r.json()
    assert body["profile"]["head_dots"] == 96
    assert body["tape"]["current"] is True
    assert body["tape"]["background"].startswith("#") and len(body["tape"]["background"]) == 7
    assert body["accent"] == "#0078d7"
    assert body["port"] == 8712
    assert body["version"] == tapesmith.__version__
    assert body["home_key"] == ctx.home_key
    assert body["pid"] == os.getpid()
    assert body["screen_px_per_mm"] is None
    assert body["ctrl_enter_only"] is False
    assert set(body["profile"]) == {"model", "head_dots", "content_dots", "content_offset", "dots_per_mm",
                                    "leader_mm", "trailer_mm", "length_factor", "verified", "experimental"}
    assert set(body["tape"]) == {"id", "name", "background", "ink", "material", "transparent", "dark",
                                 "code_mode", "density", "current"}


def test_status_cached(api):
    client, ctx = api
    r = client.get("/api/v1/status")
    assert r.status_code == 200
    body = r.json()
    assert body["view"]["chip"].startswith("P12")
    assert body["report"]["status"] is None
    assert set(body["view"]) == {"chip", "role", "title", "detail", "tooltip"}


def test_status_refresh(api):
    client, ctx = api
    transport = ctx.service._test_transport
    r = client.post("/api/v1/status/refresh", json={"quick": True})
    assert r.status_code == 200
    body = r.json()
    assert body["report"]["status"]["answered"] is True
    assert body["view"]["role"] in {"success", "secondary", "warning", "error"}
    assert any(data in STATUS_QUERIES for data in transport.written)
    assert client.post("/api/v1/status/refresh", json={}).status_code == 200


def test_status_refresh_validation(api):
    client, _ = api
    r = client.post("/api/v1/status/refresh", json={"quick": "ja"})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["kind"] == "Validierung"
    assert err["message"] == "Ungültige Anfrage: Feld ‚quick‘ muss true oder false sein"
    assert isinstance(err["details"], dict) and err["details"]["errors"]


def test_cancel_and_continue(api):
    client, _ = api
    r = client.post("/api/v1/print/cancel", json={"job_key": "unbekannt"})
    assert r.status_code == 200 and r.json() == {"cancelled": False}
    r = client.post("/api/v1/print/continue", json={})
    assert r.status_code == 200 and r.json() == {"was_pausing": False}


def test_connection_endpoints(api):
    client, _ = api
    assert client.post("/api/v1/connection/preconnect", json={}).json() == {}
    assert client.post("/api/v1/connection/disconnect", json={}).json() == {}


def test_health_closed_service(tmp_path):
    client, ctx = make_client(tmp_path)
    ctx.service.close()
    try:
        r = client.get("/health")
        assert r.status_code == 503 and r.json()["ok"] is False
    finally:
        close_ctx(ctx)


def test_service_error_mapped(api, monkeypatch):
    client, ctx = api

    def busy(**kw):
        raise PrinterBusy("belegt")

    monkeypatch.setattr(ctx.service, "status", busy)
    r = client.post("/api/v1/status/refresh", json={})
    assert r.status_code == 409
    assert r.json()["error"]["kind"] == "PrinterBusy"

    def crash(**kw):
        raise RuntimeError("geheim innen")

    monkeypatch.setattr(ctx.service, "status", crash)
    r = client.post("/api/v1/status/refresh", json={})
    assert r.status_code == 500
    assert "Traceback" not in r.text
    assert r.json()["error"]["kind"] == "RuntimeError"


# ---------- error_body ----------

@pytest.mark.parametrize("exc, status", [
    (PrinterBusy("x"), 409),
    (ConnectTimeout("x"), 503),
    (PrinterOffline("x"), 503),
    (TemplateError("x"), 422),
    (ValueError("x"), 422),
    (NotFound("x"), 404),
    (RuntimeError("x"), 500),
])
def test_error_body_status(exc, status):
    code, body = error_body(exc)
    assert code == status
    err = body["error"]
    assert set(err) == {"kind", "code", "message", "hint", "exit_code", "details"}
    assert err["kind"] == type(exc).__name__
    assert err["message"] == "x"


def test_error_body_hint_from_explain():
    exc = PrinterBusy("belegt")
    _, body = error_body(exc)
    assert body["error"]["hint"] == explain(exc).hint
    assert body["error"]["exit_code"] == explain(exc).exit_code
    _, body = error_body(NotFound("fehlt"))
    assert body["error"]["hint"] == "" and body["error"]["exit_code"] == 1


def test_error_body_no_traceback():
    try:
        raise RuntimeError("kaputt")
    except RuntimeError as exc:
        code, body = error_body(exc)
    assert code == 500
    assert "Traceback" not in str(body)


# ---------- Akzentfarbe ----------

def test_read_accent():
    assert accent.read_accent(lambda: 0xFFD77800) == "#0078d7"
    assert accent.read_accent(lambda: None) is None

    def broken():
        raise OSError("kein Schlüssel")

    assert accent.read_accent(broken) is None


# ---------- kein Qt ----------

def test_webapi_app_imports_without_qt():
    code = ("import sys, tapesmith.webapi.app, tapesmith.webapi.server; "
            "assert not any(m.startswith('PySide6') for m in sys.modules), 'PySide6 geladen'")
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")}
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr


def test_routes_core_order_and_stubs():
    from tapesmith.webapi import (routes_data, routes_editor, routes_labels, routes_settings, routes_system,
                                 routes_templates)
    from fastapi import APIRouter

    for mod in (routes_labels, routes_templates, routes_editor, routes_data, routes_settings, routes_system):
        assert isinstance(mod.router, APIRouter)


def test_static_dir_helper():
    from tapesmith import webui

    assert webui.static_dir() == Path(webui.__file__).with_name("static")


def test_gebaute_oberflaeche_hat_favicon():
    """Favicon (SVG, ICO, Touch-Icon) liegt im Build und ist in index.html verlinkt."""
    from tapesmith import webui

    static = webui.static_dir()
    for name in ("favicon.svg", "favicon.ico", "apple-touch-icon.png"):
        assert (static / name).is_file(), name
    index = (static / "index.html").read_text(encoding="utf-8")
    assert 'href="/favicon.svg"' in index and 'href="/favicon.ico"' in index


def test_validation_missing_field(api):
    client, _ = api
    r = client.post("/api/v1/print/cancel", json={})
    assert r.status_code == 422
    assert r.json()["error"]["message"] == "Ungültige Anfrage: Feld ‚job_key‘ fehlt"
    assert r.json()["error"]["details"] == {"errors": ["body.job_key"]}


def test_unknown_api_post_is_404(api):
    client, _ = api
    r = client.post("/api/v1/gibtsnicht", json={})
    assert r.status_code == 404 and r.json()["error"]["kind"] == "NotFound"
