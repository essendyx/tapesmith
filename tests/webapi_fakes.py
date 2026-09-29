"""Gemeinsame Fakes für die Tests der Web-API (kein Port, kein uvicorn, kein Druck)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from daemon_fakes import close_service, make_service
from tapesmith import config as config_mod
from tapesmith import paths
from tapesmith.webapi.app import create_app
from tapesmith.webapi.context import ApiContext
from tapesmith.webapi.events import EventBroker

TOKEN = "test-token"
BASE_URL = "http://127.0.0.1:8712"
HOME_KEY = "test-home"


def write_base_config(extra: dict | None = None) -> Path:
    """Ergänzt `<TAPESMITH_HOME>/config.json` um `transport: "memory"` (falls fehlend) und `extra`."""
    path = paths.config_path()
    import json

    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    updates = {} if "transport" in data else {"transport": "memory"}
    updates.update(extra or {})
    config_mod.save_config(updates)
    return path


def _default_static(tmp_path: Path) -> Path:
    static = tmp_path / "webstatic" / "static"
    (static / "assets").mkdir(parents=True, exist_ok=True)
    (static / "index.html").write_text("<!doctype html><title>P12</title>", encoding="utf-8")
    (static / "assets" / "app.js").write_text("console.log('p12');", encoding="utf-8")
    return static


def make_ctx(tmp_path, *, service=None, static_dir=None, config: dict | None = None, sync_config: bool = True,
             **ctx_kwargs) -> ApiContext:
    transport = None
    if service is None:
        if sync_config:
            write_base_config(config)
            service, transport = make_service(tmp_path, config_loader=config_mod.load_config)
        else:
            service, transport = make_service(tmp_path, config=config)
        service._test_transport = transport
    kwargs = dict(port=8712, accent_reader=lambda: "#0078d7")
    kwargs.update(ctx_kwargs)
    return ApiContext(service=service, home_key=HOME_KEY, token=TOKEN, broker=EventBroker(),
                      static_dir=static_dir if static_dir is not None else _default_static(tmp_path), **kwargs)


def make_client(tmp_path, *, client_ip: str = "127.0.0.1", lan=None, tokens=None, auth: str | None = "session",
                base_url: str = BASE_URL, **kwargs) -> tuple[TestClient, ApiContext]:
    """TestClient an der App. Standard: Loopback-Client mit Sitzungs-Token (wie bisher).

    `lan`: `LanPolicy` oder None (LAN aus); `tokens`: Objekt mit `verify` (Standard: echter
    `TokenStore` im Temp-Home); `auth="session"` sendet `X-P12-Token: test-token`, `auth=None`
    keinen Kopf, sonst wird `auth` als Bearer-Token gesendet. `limiter=` usw. gehen an `make_ctx`.
    """
    if lan is not None:
        kwargs["lan"] = lan
    if tokens is not None:
        kwargs["tokens"] = tokens
    ctx = make_ctx(tmp_path, **kwargs)
    if auth == "session":
        headers = {"X-P12-Token": TOKEN}
    elif auth is None:
        headers = {}
    else:
        headers = {"Authorization": f"Bearer {auth}"}
    client = TestClient(create_app(ctx), base_url=base_url, headers=headers, client=(client_ip, 50123))
    return client, ctx


def make_token(ctx: ApiContext, role: str, name: str | None = None) -> str:
    """Legt in `ctx.tokens` ein API-Token an und liefert den Klartext."""
    _info, secret = ctx.tokens.create(name or f"test-{role}-{len(ctx.tokens.list())}", role)
    return secret


def close_ctx(ctx) -> None:
    try:
        ctx.broker.close_all()
        ctx.close()
    finally:
        close_service(ctx.service)
