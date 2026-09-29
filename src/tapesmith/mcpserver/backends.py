"""Zugang der MCP-Werkzeuge zum Druckdienst.

`FacadeBackend` läuft im Dienst (Streamable HTTP unter `/mcp`) und druckt über die Fassade mit der
Quelle `mcp`. `HttpBackend` dient dem stdio-Server `p12 mcp`: er druckt nie selbst, sondern spricht
per HTTP mit dem lokalen Druckdienst (Sitzung aus `session.json`, Kopf `X-P12-Source: mcp`).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Protocol

import httpx

from tapesmith import config, sourcelimits
from tapesmith.i18n import _t

log = logging.getLogger(__name__)

ORIGIN = "mcp"
API = "/api/v1"


class McpToolError(Exception):
    """Fehler, den das Werkzeug als Klartext an Claude meldet (nie ein Traceback)."""


class McpBackend(Protocol):
    def templates(self) -> list[dict]: ...
    def render(self, source: dict, options: dict | None) -> dict: ...
    def print(self, source: dict, options: dict | None) -> dict: ...
    def status(self) -> dict: ...
    def history(self, limit: int, query: str) -> list[dict]: ...
    def queue(self) -> dict: ...
    def copy_limit(self) -> int: ...


def _limits_from(cfg: dict) -> tuple[int, str]:
    return sourcelimits.max_copies(cfg, ORIGIN), sourcelimits.limits_text(cfg, ORIGIN)


class FacadeBackend:
    """Im Dienst: `LabelFacade` mit Quelle `mcp`."""

    def __init__(self, facade):
        self.facade = facade

    def templates(self) -> list[dict]:
        return self.facade.template_summaries()

    def render(self, source: dict, options: dict | None) -> dict:
        return self.facade.render(source, options, origin=ORIGIN)

    def print(self, source: dict, options: dict | None) -> dict:
        from tapesmith.webapi.labels import LabelNotPrintable

        try:
            return self.facade.print(source, options, origin=ORIGIN)
        except LabelNotPrintable as exc:
            raise McpToolError(_t("Label nicht druckbar: {exc}", exc=exc)) from exc

    def status(self) -> dict:
        return self.facade.status()

    def history(self, limit: int, query: str) -> list[dict]:
        return self.facade.history(limit, query)

    def queue(self) -> dict:
        return self.facade.queue()

    def copy_limit(self) -> int:
        return _limits_from(self.facade.config())[0]

    def limits_text(self) -> str:
        return _limits_from(self.facade.config())[1]


def _default_session_loader() -> dict:
    from tapesmith.webui.browser import connect_session

    return connect_session(config.load_config())


def _error_message(response: httpx.Response) -> str:
    try:
        error = response.json().get("error") or {}
    except (ValueError, AttributeError):
        error = {}
    if not isinstance(error, dict) or not error:
        return _t("Druckdienst antwortet mit HTTP {status_code}", status_code=response.status_code)
    message = str(error.get("message") or f"HTTP {response.status_code}")
    details = error.get("details") if isinstance(error.get("details"), dict) else {}
    if error.get("kind") == "Label":
        errors = [str(e) for e in details.get("errors") or []] or [message]
        return _t("Label nicht druckbar: ") + "; ".join(errors)
    hint = str(error.get("hint") or "").strip()
    return _t("{message} (Hinweis: {hint})", message=message, hint=hint) if hint else message


class HttpBackend:
    """Für stdio: HTTP gegen den lokalen Druckdienst mit dem Sitzungs-Token."""

    def __init__(self, *, session_loader: Callable[[], dict] = _default_session_loader,
                 client_factory: Callable[..., httpx.Client] = httpx.Client, timeout_s: float = 60.0,
                 config_loader: Callable[[], dict] = config.load_config):
        self._session_loader = session_loader
        self._client_factory = client_factory
        self._timeout_s = timeout_s
        self._config_loader = config_loader
        self._client: httpx.Client | None = None
        self._lock = threading.Lock()

    # ---------- Verbindung ----------

    def _connect(self) -> httpx.Client:
        try:
            session = self._session_loader()
        except Exception as exc:  # noqa: BLE001: jede Ursache als Klartext an Claude
            raise McpToolError(_t("Druckdienst nicht erreichbar: {exc}", exc=exc)) from exc
        if not isinstance(session, dict) or not session.get("port") or not session.get("token"):
            raise McpToolError(_t("Druckdienst nicht erreichbar: keine gültige Sitzung (session.json)"))
        headers = {"X-P12-Token": str(session["token"]), "X-P12-Source": ORIGIN}
        return self._client_factory(base_url=f"http://127.0.0.1:{int(session['port'])}", headers=headers,
                                    timeout=self._timeout_s)

    def _drop(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:  # noqa: BLE001: nur Aufräumen
                pass
            self._client = None

    def close(self) -> None:
        with self._lock:
            self._drop()

    def _request(self, method: str, path: str, **kw) -> object:
        with self._lock:
            for attempt in range(2):
                if self._client is None:
                    self._client = self._connect()
                try:
                    response = self._client.request(method, API + path, **kw)
                except httpx.HTTPError as exc:
                    self._drop()
                    raise McpToolError(_t("Druckdienst nicht erreichbar: {exc}", exc=exc)) from exc
                if response.status_code == 401:
                    self._drop()
                    if attempt == 0:
                        log.info("MCP: Sitzung abgelehnt, lade session.json neu")
                        continue
                    raise McpToolError(_t("Nicht angemeldet beim Druckdienst: Sitzungs-Token ungültig (Dienst neu gestartet?)"))
                if response.status_code >= 400:
                    raise McpToolError(_error_message(response))
                try:
                    return response.json()
                except ValueError as exc:
                    raise McpToolError(_t("Druckdienst lieferte keine gültige Antwort")) from exc
        raise McpToolError(_t("Druckdienst nicht erreichbar"))  # pragma: no cover

    # ---------- Werkzeug-Schnittstelle ----------

    def templates(self) -> list[dict]:
        return list(self._request("GET", "/templates").get("templates", []))

    def render(self, source: dict, options: dict | None) -> dict:
        return self._request("POST", "/labels/render", json={"source": source, "options": options})

    def print(self, source: dict, options: dict | None) -> dict:
        return self._request("POST", "/labels/print", json={"source": source, "options": options})

    def status(self) -> dict:
        return self._request("GET", "/status")

    def history(self, limit: int, query: str) -> list[dict]:
        data = self._request("GET", "/history", params={"query": query, "limit": limit})
        return list(data.get("entries", []))

    def queue(self) -> dict:
        return self._request("GET", "/queue")

    def _config(self) -> dict:
        try:
            return self._config_loader()
        except Exception as exc:  # noqa: BLE001: kaputte Konfiguration ergibt die Standardgrenzen
            log.warning("MCP: Konfiguration nicht lesbar, verwende Standardgrenzen: %s", exc)
            return {}

    def copy_limit(self) -> int:
        return _limits_from(self._config())[0]

    def limits_text(self) -> str:
        return _limits_from(self._config())[1]
