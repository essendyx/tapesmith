"""MCP-Server mit dem offiziellen Python-SDK (`mcp` 2.x, `MCPServer`).

Zwei Wege mit denselben Werkzeugen:
- stdio (`p12 mcp`): `run_stdio()` mit `HttpBackend` gegen den lokalen Druckdienst. Auf stdout
  steht nur das Protokoll, Logs gehen nach `<App-Verzeichnis>\\logs\\mcp.log` und stderr.
- Streamable HTTP (`/mcp` im Dienst): `http_app(backend_getter)` liefert eine ASGI-App ohne eigene
  Weiterleitung und eine Lifespan-Fabrik für `app.state.lifespans`.
"""

from __future__ import annotations

import contextlib
import inspect
import json
import logging
import sys
from collections.abc import AsyncIterator, Callable
from typing import Annotated, Any

from mcp.server.mcpserver import Image, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import Field

from tapesmith.mcpserver.backends import HttpBackend, McpBackend, McpToolError
from tapesmith.mcpserver.tools import P12Tools, PreviewCache
from tapesmith.i18n import N_, _t

log = logging.getLogger(__name__)

SERVER_NAME = "tapesmith"
MCP_PATH = "/mcp"

INSTRUCTIONS = (
    N_("Werkzeuge für den Labeldrucker Phomemo P12 (12 mm Band). Ablauf beim Drucken, immer so: 1. Mit list_templates passende Vorlagen und ihre Felder finden (oder freien Text mit 1 bis 3 Zeilen nehmen). 2. label_preview aufrufen und die gelieferte Vorschau (Bild) dem Nutzer zeigen, dazu Warnungen und Rückfragegründe (reasons) nennen. 3. Den Nutzer ausdrücklich fragen, ob gedruckt werden soll. 4. Nur nach seiner Zustimmung label_print mit der preview_id und confirm=true aufrufen. Nie ohne Zustimmung drucken und confirm=true nie auf Verdacht setzen. Liefert label_preview ok=false, wird nicht gedruckt; die Gründe dem Nutzer nennen. Status, Verlauf und Warteschlange lassen sich mit printer_status, print_history und queue_list abfragen.")
)

StrictBool = Annotated[bool, Field(strict=True)]
StrictInt = Annotated[int, Field(strict=True)]

ASGIApp = Callable[..., Any]


def _run(fn: Callable[[], Any]) -> Any:
    """Führt ein Werkzeug aus; erwartete Fehler werden zu Tool-Fehlern mit Klartext."""
    try:
        return fn()
    except ToolError:
        raise
    except McpToolError as exc:
        raise ToolError(str(exc)) from exc
    except (ValueError, LookupError) as exc:
        text = str(exc.args[0]) if isinstance(exc, KeyError) and exc.args else str(exc)
        raise ToolError(text or type(exc).__name__) from exc


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def build_server(backend: McpBackend | None = None, *, http: bool = False,
                 backend_getter: Callable[[], McpBackend] | None = None,
                 cache: PreviewCache | None = None) -> MCPServer:
    """`MCPServer` mit den sechs Werkzeugen. Die Werkzeuge holen ihr Backend in jedem Aufruf über
    `backend_getter` (Standard: immer `backend`); die Vorschauen liegen in einem gemeinsamen Cache,
    damit `preview_id` auch über zustandslose HTTP-Anfragen hinweg gilt. `http` setzt nur die
    Bezeichnung (Transporte baut `http_app` bzw. `run_stdio`)."""
    if backend_getter is None:
        if backend is None:
            raise ValueError(_t("build_server braucht backend oder backend_getter"))
        backend_getter = lambda: backend  # noqa: E731
    shared_cache = cache if cache is not None else PreviewCache()

    def tools() -> P12Tools:
        return P12Tools(backend_getter(), shared_cache)

    server = MCPServer(SERVER_NAME, title="Tapesmith", instructions=_t(INSTRUCTIONS),
                       description="Labeldrucker Phomemo P12" + (" (HTTP)" if http else ""),
                       log_level="WARNING")

    def tool(fn):
        # Beschreibung ohne Einrückung der Docstrings (Claude sieht sie als Werkzeugbeschreibung)
        server.add_tool(fn, description=inspect.cleandoc(fn.__doc__ or ""))
        return fn

    @tool
    def list_templates(query: str = "") -> str:
        """Listet die Label-Vorlagen mit ihren Eingabefeldern (id, label, type, required, choices, default).
        `query` filtert nach Name, Beschreibung, Kategorie und Schlagworten (ohne Groß-/Kleinschreibung)."""
        return _json(_run(lambda: tools().list_templates(query)))

    @tool
    def label_preview(template: str | None = None, values: dict[str, str] | None = None,
                      text: list[str] | None = None, copies: StrictInt = 1) -> list:
        """Erzeugt die Vorschau eines Labels, druckt aber nichts. Genau eins angeben: `template`
        (Vorlagenname, Werte in `values` als Feld-ID: Text) oder `text` (1 bis 3 Zeilen). `copies`
        1 bis 5 (Grenze aus guard.confirm_copies). Liefert JSON (ok, preview_id, Warnungen, Rückfragegründe)
        und das Vorschaubild. Das Bild dem Nutzer zeigen und erst nach seiner Zustimmung label_print
        mit der preview_id und confirm=true aufrufen. Ohne preview_id (ok=false) ist kein Druck möglich."""
        result, png = _run(lambda: tools().label_preview(template=template, values=values, text=text,
                                                         copies=copies))
        content: list = [_json(result)]
        if png:
            content.append(Image(data=png, format="png"))
        return content

    @tool
    def label_print(preview_id: str, confirm: StrictBool = False) -> str:
        """Druckt eine zuvor mit label_preview erzeugte und dem Nutzer gezeigte Vorschau. Nur aufrufen,
        wenn der Nutzer dem Druck ausdrücklich zugestimmt hat, dann mit confirm=true. Ohne confirm=true
        wird nie gedruckt. Eine preview_id gilt 15 Minuten und nur für einen Druck."""
        return _json(_run(lambda: tools().label_print(preview_id, confirm=confirm)))

    @tool
    def printer_status() -> str:
        """Zustand des Druckers (verbunden, Akku, Deckel) aus dem Druckdienst, ohne den Drucker zu wecken."""
        return _json(_run(lambda: tools().printer_status()))

    @tool
    def print_history(limit: StrictInt = 10, query: str = "") -> str:
        """Die letzten Druckaufträge (id, Zeitpunkt, Titel, Vorlage, Quelle, Status, Kopien), neueste zuerst.
        `limit` 1 bis 100, `query` sucht im Verlauf."""
        return _json(_run(lambda: tools().print_history(limit=limit, query=query)))

    @tool
    def queue_list() -> str:
        """Warteschlange des Druckdienstes: pausiert, Wartegrund und Aufträge mit Zustand und letztem Fehler."""
        return _json(_run(lambda: tools().queue_list()))

    return server


# ---------------------------------------------------------------- stdio


def _setup_stdio_logging() -> None:
    """Logs nie auf stdout: Datei `mcp.log` im Log-Ordner, Warnungen zusätzlich nach stderr."""
    from tapesmith import paths

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        handler: logging.Handler = logging.FileHandler(paths.log_dir() / "mcp.log", encoding="utf-8")
        handler.setFormatter(fmt)
        root.addHandler(handler)
    except OSError:
        pass
    err = logging.StreamHandler(sys.stderr)
    err.setLevel(logging.WARNING)
    err.setFormatter(fmt)
    root.addHandler(err)


def run_stdio(backend: McpBackend | None = None) -> None:
    """stdio-Server für Claude Code; der Prozess druckt nie selbst (HTTP zum lokalen Dienst)."""
    _setup_stdio_logging()
    backend = backend if backend is not None else HttpBackend()
    server = build_server(backend)
    try:
        server.run("stdio")
    finally:
        close = getattr(backend, "close", None)
        if callable(close):
            close()


# ---------------------------------------------------------------- Streamable HTTP


class McpHttpApp:
    """ASGI-App für `/mcp`: je Lifespan ein frischer Sitzungsmanager (zustandslos, JSON-Antworten),
    Vorschauen über alle Anfragen hinweg im selben Cache."""

    def __init__(self, backend_getter: Callable[[], McpBackend]):
        self._backend_getter = backend_getter
        self._cache = PreviewCache()
        self._manager = None

    def _new_manager(self):
        server = build_server(http=True, backend_getter=self._backend_getter, cache=self._cache)
        # DNS-Rebinding-Schutz des SDK aus: Host, Origin und Token prüft die eigene Middleware.
        server.streamable_http_app(streamable_http_path=MCP_PATH, json_response=True, stateless_http=True,
                                   transport_security=TransportSecuritySettings(
                                       enable_dns_rebinding_protection=False))
        return server.session_manager

    @contextlib.asynccontextmanager
    async def lifespan(self) -> AsyncIterator[None]:
        manager = self._new_manager()
        async with manager.run():
            self._manager = manager
            try:
                yield
            finally:
                self._manager = None

    async def __call__(self, scope, receive, send) -> None:
        manager = self._manager
        if manager is None:
            from starlette.responses import JSONResponse

            body = {"error": {"kind": "Unavailable", "message": _t("MCP ist noch nicht bereit"), "hint": "",
                              "exit_code": 1, "details": None}}
            await JSONResponse(body, status_code=503)(scope, receive, send)
            return
        await manager.handle_request(scope, receive, send)


def http_app(backend_getter: Callable[[], McpBackend]) -> tuple[ASGIApp, Callable[[], Any]]:
    """(ASGI-App, Lifespan-Fabrik) für Streamable HTTP unter `/mcp`."""
    app = McpHttpApp(backend_getter)
    return app, app.lifespan
