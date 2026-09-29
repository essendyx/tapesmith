"""MCP über Streamable HTTP unter `/mcp`.

`POST /mcp` wird direkt bedient (keine Weiterleitung auf `/mcp/`): die Route steht in
`app.router.routes` vor der statischen Auslieferung. Token und Rolle (`admin`, `drucken`) prüft die
Middleware (`security.py`), die Quelle ist dort immer `mcp`. Ist `mcp.http` aus, antwortet `/mcp`
mit 404 (je Anfrage geprüft, Umschalten wirkt ohne Neustart). Fehlt das SDK, läuft der Dienst
ohne MCP weiter.
"""

from __future__ import annotations

import logging

from starlette.responses import JSONResponse
from starlette.routing import Route

from tapesmith import config as config_mod
from tapesmith.webapi.errors import http_error_body
from tapesmith.i18n import _t

log = logging.getLogger(__name__)

MCP_PATH = "/mcp"


class _McpGate:
    """Prüft `mcp.http` und die Methode, dann weiter an die SDK-App."""

    def __init__(self, inner, ctx):
        self.inner = inner
        self.ctx = ctx

    def _enabled(self) -> bool:
        try:
            return bool(config_mod.setting(self.ctx.config(), "mcp.http"))
        except Exception as exc:  # noqa: BLE001: kaputte Konfiguration schaltet MCP ab
            log.warning("MCP: Konfiguration nicht lesbar, /mcp aus: %s", exc)
            return False

    async def __call__(self, scope, receive, send) -> None:
        if not self._enabled():
            await JSONResponse(http_error_body(404, _t("Nicht gefunden: MCP über HTTP ist aus (mcp.http)")),
                               status_code=404)(scope, receive, send)
            return
        if scope.get("method") != "POST":
            # zustandslos mit JSON-Antworten: kein SSE-Strom per GET, keine Sitzungen per DELETE.
            # 404 wie jeder andere unbekannte Pfad unter /mcp (nie die Oberfläche).
            await JSONResponse(http_error_body(404, _t("Nicht gefunden: /mcp nimmt nur POST an")),
                               status_code=404)(scope, receive, send)
            return
        await self.inner(scope, receive, send)


def mount(app, ctx) -> None:
    """Hängt `/mcp` an die App und die Lifespan-Fabrik an `app.state.lifespans`."""
    try:
        from tapesmith.automation.facade import LabelFacade
        from tapesmith.mcpserver.backends import FacadeBackend
        from tapesmith.mcpserver.server import http_app
    except ImportError as exc:
        log.warning("MCP über HTTP nicht verfügbar (Paket mcp fehlt?): %s", exc)
        return
    inner, lifespan = http_app(lambda: FacadeBackend(LabelFacade.from_ctx(ctx)))
    app.router.routes.append(Route(MCP_PATH, endpoint=_McpGate(inner, ctx)))
    app.state.lifespans.append(lifespan)
