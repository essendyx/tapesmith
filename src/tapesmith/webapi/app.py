"""FastAPI-App der lokalen API und Auslieferung der Web-Oberfläche.

Bewusste Abweichung: keine Swagger UI (`docs_url=None`, `redoc_url=None`), weil sie
Skripte von einem CDN lädt und das Token nicht senden kann. Stattdessen liefert `GET /api/v1/docs`
(`routes_short`) eine schlichte HTML-Übersicht ohne Skripte. Das Schema liegt unter
`/api/v1/openapi.json` und braucht wie jede API-Route das Token.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from tapesmith.webapi import homelab_routers
from tapesmith.webapi import (mcp_http, routes_access, routes_core, routes_data, routes_drafts, routes_editor,
                             routes_family, routes_labels, routes_modules, routes_settings, routes_short,
                             routes_logs, routes_secrets, routes_support, routes_system, routes_templates,
                             routes_update)
from tapesmith.webapi.context import ApiContext
from tapesmith.webapi.errors import http_error_body, install_handlers
from tapesmith.webapi.language import LanguageMiddleware
from tapesmith.webapi.security import SecurityMiddleware
from tapesmith.i18n import N_, _t

API_PREFIX = "/api/v1"
ASSET_CACHE = "public, max-age=31536000, immutable"
NOT_BUILT_HTML = N_("""<!doctype html>
<html lang="de"><head><meta charset="utf-8"><title>Tapesmith</title></head>
<body style="font-family: 'Segoe UI', sans-serif; margin: 2rem">
<h1>Oberfläche nicht gebaut</h1>
<p>Oberfläche nicht gebaut: python tools/build_web.py ausführen</p>
</body></html>
""")


def _not_found() -> JSONResponse:
    return JSONResponse(http_error_body(404, _t("Nicht gefunden")), status_code=404)


def _resolve_static(static_dir: Path, rel: str) -> Path | None:
    """Datei innerhalb von `static_dir` oder None (nie außerhalb, auch nicht über `..`)."""
    if not rel or "\\" in rel or "\x00" in rel:
        return None
    try:
        root = static_dir.resolve()
        target = (root / rel).resolve()
    except (OSError, ValueError):
        return None
    if target == root or not target.is_relative_to(root):
        return None
    return target if target.is_file() else None


def _reserved(path: str) -> bool:
    """Pfade der API und von MCP liefern nie die Oberfläche aus."""
    return any(path == p or path.startswith(p + "/") for p in ("api", "mcp"))


def _static_route(app: FastAPI) -> None:
    @app.api_route("/api/{rest:path}", methods=["POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
    def unknown_api(rest: str):
        return _not_found()

    @app.api_route("/mcp", methods=["POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
    @app.api_route("/mcp/{rest:path}", methods=["POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
    def unknown_mcp(rest: str = ""):
        return _not_found()

    @app.get("/{path:path}", include_in_schema=False)
    def static(path: str):
        if _reserved(path):
            return _not_found()
        static_dir: Path = app.state.ctx.static_dir
        file = _resolve_static(static_dir, path)
        if file is not None:
            if path.startswith("assets/"):
                return FileResponse(file, headers={"Cache-Control": ASSET_CACHE})
            if file.name == "index.html":
                return FileResponse(file, headers={"Cache-Control": "no-store"})
            return FileResponse(file)
        last = path.rsplit("/", 1)[-1]
        if "." in last:
            return _not_found()
        index = static_dir / "index.html"
        if index.is_file():
            return FileResponse(index, headers={"Cache-Control": "no-store"})
        return HTMLResponse(_t(NOT_BUILT_HTML), headers={"Cache-Control": "no-store"})


@contextlib.asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Betritt alle Einträge aus `app.state.lifespans` (z. B. MCP-Sitzungen) und verlässt sie
    in umgekehrter Reihenfolge."""
    async with contextlib.AsyncExitStack() as stack:
        for factory in list(getattr(app.state, "lifespans", ())):
            await stack.enter_async_context(factory())
        yield


def create_app(ctx: ApiContext) -> FastAPI:
    # `module_gate` sperrt die Routen ausgeschalteter Module (tapesmith.modules).
    app = FastAPI(title="Tapesmith", docs_url=None, redoc_url=None, openapi_url=f"{API_PREFIX}/openapi.json",
                  lifespan=_lifespan, dependencies=[Depends(routes_modules.module_gate)])
    app.state.ctx = ctx
    app.state.lifespans = []
    install_handlers(app)
    routes_modules.install(app)
    app.include_router(routes_core.health_router)
    for module in (routes_core, routes_short, routes_labels, routes_templates, routes_editor, routes_drafts,
                   routes_data, routes_settings, routes_system, routes_access, routes_family, routes_support,
                   routes_update, routes_modules, routes_secrets, routes_logs):
        app.include_router(module.router, prefix=API_PREFIX)
    homelab_routers.install(app, API_PREFIX)
    mcp_http.mount(app, ctx)
    _static_route(app)
    app.add_middleware(SecurityMiddleware, token_getter=lambda: ctx.token, port_getter=lambda: ctx.port,
                       tokens_getter=lambda: ctx.tokens, lan_getter=lambda: ctx.lan,
                       limiter_getter=lambda: ctx.limiter)
    # Zuletzt hinzugefügt, also außen: auch Meldungen der Sicherheitsschicht folgen der Sprache.
    app.add_middleware(LanguageMiddleware)
    return app
