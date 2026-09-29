"""Test-Hilfen der Homelab-Integrationen: Fake-Keyring, MockTransport, Einstellungsdatei,
Token-Dateien und ein TestClient für einzelne Router. Nie echtes Netz, nie echte Tokens."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tapesmith import paths
from tapesmith.webapi import errors as api_errors
from tapesmith.webapi import homelab_common
from tapesmith.webapi.context import ApiContext
from webapi_fakes import BASE_URL, make_ctx

DATA = Path(__file__).parent / "data"


class FakeKeyring:
    """Ersatz für das Paket `keyring` (get_password/set_password/delete_password)."""

    def __init__(self, entries: dict[tuple[str, str], str] | None = None):
        self.entries: dict[tuple[str, str], str] = dict(entries or {})

    def get_password(self, service: str, user: str) -> str | None:
        return self.entries.get((service, user))

    def set_password(self, service: str, user: str, value: str) -> None:
        self.entries[(service, user)] = value

    def delete_password(self, service: str, user: str) -> None:
        self.entries.pop((service, user), None)


def _response(value: Any, request: httpx.Request) -> httpx.Response:
    if isinstance(value, httpx.Response):
        return value
    if callable(value):
        return value(request)
    if isinstance(value, tuple):
        status, body = value
        if isinstance(body, (dict, list)):
            return httpx.Response(status, json=body)
        if isinstance(body, bytes):
            return httpx.Response(status, content=body)
        if body is None:
            return httpx.Response(status)
        return httpx.Response(status, text=str(body))
    return httpx.Response(200, json=value)


def mock_transport(routes: Mapping[str, Any], *, calls: list | None = None) -> httpx.MockTransport:
    """MockTransport mit Antworten je `"<METHOD> <pfad>?<query>"` (exakt) bzw. `"<METHOD> <pfad>"`.

    Unbekannte Anfrage: Status 599 mit Text "unerwartete Anfrage <METHOD> <URL>"."""

    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request)
        path = request.url.path
        query = request.url.query.decode() if isinstance(request.url.query, bytes) else str(request.url.query)
        exact = f"{request.method} {path}?{query}" if query else None
        if exact is not None and exact in routes:
            return _response(routes[exact], request)
        plain = f"{request.method} {path}"
        if plain in routes:
            return _response(routes[plain], request)
        return httpx.Response(599, text=f"unerwartete Anfrage {request.method} {request.url}")

    return httpx.MockTransport(handler)


def connect_error_transport() -> httpx.MockTransport:
    """Transport, der jede Anfrage mit `httpx.ConnectError` abbricht."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Verbindung abgelehnt", request=request)

    return httpx.MockTransport(handler)


class FakeShortlinkService:
    """Zustandsbehafteter Kurz-Link-Dienst (PUT/GET/DELETE /api/links/{id}) als MockTransport."""

    def __init__(self):
        self.links: dict[str, dict] = {}
        self.calls: list[httpx.Request] = []
        self.transport = httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        parts = request.url.path.strip("/").split("/")
        if parts[:2] != ["api", "links"] or len(parts) != 3:
            return httpx.Response(599, text=f"unerwartete Anfrage {request.method} {request.url}")
        link_id = parts[2]
        if request.method == "GET":
            link = self.links.get(link_id)
            return httpx.Response(200, json=link) if link else httpx.Response(404, json={"error": "x"})
        if request.method == "PUT":
            body = json.loads(request.content)
            existed = link_id in self.links
            link = self.links.setdefault(link_id, {"id": link_id, "target": None, "note": "",
                                                   "created": "", "updated": "", "hits": 0})
            link["target"] = body.get("target")
            if "note" in body:
                link["note"] = body["note"] or ""
            return httpx.Response(200 if existed else 201, json=link)
        if request.method == "DELETE":
            return httpx.Response(204 if self.links.pop(link_id, None) else 404)
        return httpx.Response(599, text=f"unerwartete Anfrage {request.method} {request.url}")

    def writes(self) -> list[httpx.Request]:
        return [c for c in self.calls if c.method in ("PUT", "POST", "DELETE")]


def write_homelab(data: dict) -> Path:
    """Schreibt `<TAPESMITH_HOME>/homelab.json`."""
    path = paths.app_dir() / "homelab.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def token_file(tmp_path, name: str, value: str = "test-token-123") -> str:
    """Legt eine Token-Datei unter `tmp_path/tokens` an und gibt `"file:<pfad>"` zurück."""
    folder = Path(tmp_path) / "tokens"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(value + "\n", encoding="utf-8")
    return f"file:{path}"


def missing_refs(tmp_path) -> dict:
    """Einstellungen, deren Token-Referenzen auf nicht vorhandene Dateien unter `tmp_path` zeigen
    (Tests lesen so nie echte Token-Dateien)."""
    folder = Path(tmp_path) / "no-tokens"
    return {
        "paperless": {"token_ref": f"file:{folder / 'paperless'}"},
        "shortlink": {"token_ref": f"file:{folder / 'shortlink'}"},
        "homeassistant": {"token_ref": f"file:{folder / 'ha'}"},
    }


def router_client(tmp_path, *routers, extras: dict | None = None,
                  **ctx_kw) -> tuple[TestClient, ApiContext]:
    """TestClient für einzelne Router unter `/api/v1` (ohne Sicherheits-Middleware)."""
    ctx = make_ctx(tmp_path, **ctx_kw)
    ctx.extras.update(extras or {})
    app = FastAPI()
    app.state.ctx = ctx
    api_errors.install_handlers(app)
    homelab_common.install_integration_handler(app)
    for router in routers:
        app.include_router(router, prefix=homelab_common.API_PREFIX)
    return TestClient(app, base_url=BASE_URL), ctx


def load_json(rel: str):
    """`tests/data/<rel>` als JSON."""
    return json.loads((DATA / rel).read_text(encoding="utf-8"))


Handler = Callable[[httpx.Request], httpx.Response]
