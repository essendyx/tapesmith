"""Minimaler MCP-Client (Streamable HTTP, JSON-RPC 2.0) über httpx.

Ersetzt das Paket `mcp` für genau einen Zweck: Werkzeuge eines MCP-Servers aufrufen. Ablauf:
`initialize` (Sitzungs-ID aus `Mcp-Session-Id` merken), `notifications/initialized`, dann je Aufruf
`tools/call`. Antworten kommen als JSON oder als `text/event-stream`; bei SSE zählt die JSON-RPC-Antwort
mit passender `id`, Benachrichtigungen davor werden übergangen. Netz- und HTTP-Fehler wie `httpclient`.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import httpx

from tapesmith.integrations.errors import NotConfigured, UpstreamError
from tapesmith.integrations.httpclient import make_client, request_raw
from tapesmith.i18n import _t

PROTOCOL_VERSION = "2025-06-18"
ACCEPT = "application/json, text/event-stream"


def _version() -> str:
    try:
        from tapesmith import __version__
    except ImportError:
        return "0"
    return str(__version__)


def parse_sse(text: str) -> list[Any]:
    """JSON-Objekte aus einem `text/event-stream`: `data:`-Zeilen je Ereignis zusammengefügt."""
    messages: list[Any] = []
    data: list[str] = []

    def flush() -> None:
        if data:
            payload = "\n".join(data)
            data.clear()
            try:
                messages.append(json.loads(payload))
            except ValueError:
                pass

    for raw in text.splitlines():
        line = raw.rstrip("\r")
        if not line:
            flush()
            continue
        if line.startswith(":"):
            continue
        field, _, value = line.partition(":")
        if field == "data":
            data.append(value[1:] if value.startswith(" ") else value)
    flush()
    return messages


class McpClient:
    """Werkzeug-Aufrufe an einen MCP-Server (Streamable HTTP)."""

    def __init__(self, url: str, *, service: str = "Obsidian", timeout_s: float = 10.0,
                 transport: httpx.BaseTransport | None = None):
        self.url = url
        self.service = service
        self._client = make_client(url, service=service, timeout_s=timeout_s, transport=transport,
                                   headers={"Accept": ACCEPT, "Content-Type": "application/json"})
        self._session: str | None = None
        self._protocol: str | None = None
        self._initialized = False
        self._next_id = 1

    # ---------- Transport ----------

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self._session:
            headers["Mcp-Session-Id"] = self._session
        if self._protocol:
            headers["MCP-Protocol-Version"] = self._protocol
        return headers

    def _post(self, message: dict) -> httpx.Response:
        body = json.dumps(message, ensure_ascii=False).encode("utf-8")
        return request_raw(self._client, "POST", self.url, service=self.service, ok=(200, 202, 404),
                           content=body, headers=self._headers())

    def _new_id(self) -> int:
        value = self._next_id
        self._next_id += 1
        return value

    def _response_for(self, response: httpx.Response, request_id: int) -> dict:
        content_type = response.headers.get("content-type", "").lower()
        if "text/event-stream" in content_type:
            candidates = parse_sse(response.text)
        else:
            try:
                parsed = response.json()
            except ValueError as exc:
                raise UpstreamError(self.service, _t("MCP-Antwort ist kein JSON")) from exc
            candidates = parsed if isinstance(parsed, list) else [parsed]
        for message in candidates:
            if isinstance(message, dict) and message.get("id") == request_id and (
                    "result" in message or "error" in message):
                return message
        raise UpstreamError(self.service, _t("MCP-Antwort ohne Ergebnis"))

    def _rpc(self, method: str, params: Mapping[str, Any]) -> tuple[httpx.Response, dict | None]:
        request_id = self._new_id()
        response = self._post({"jsonrpc": "2.0", "id": request_id, "method": method, "params": dict(params)})
        if response.status_code == 404:
            return response, None
        if response.status_code == 202:
            raise UpstreamError(self.service, _t("MCP-Antwort ohne Ergebnis"))
        message = self._response_for(response, request_id)
        error = message.get("error")
        if error is not None:
            code = error.get("code", "?") if isinstance(error, dict) else "?"
            text = error.get("message", "") if isinstance(error, dict) else str(error)
            raise UpstreamError(self.service, _t("MCP-Fehler {code}: {text}", code=code, text=text))
        return response, message

    # ---------- Sitzung ----------

    def _initialize(self) -> None:
        self._session = None
        self._protocol = None
        params = {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                  "clientInfo": {"name": "tapesmith", "version": _version()}}
        response, message = self._rpc("initialize", params)
        if message is None:
            raise UpstreamError(self.service, _t("Nicht gefunden: {url}", url=self.url),
                                hint=_t("obsidian.mcp_url prüfen (Pfad meist /mcp)"))
        result = message.get("result") or {}
        self._session = response.headers.get("mcp-session-id") or None
        self._protocol = str(result.get("protocolVersion") or PROTOCOL_VERSION)
        notify = self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        if notify.status_code == 404:
            raise UpstreamError(self.service, _t("Nicht gefunden: {url}", url=self.url))
        self._initialized = True

    def call_tool(self, name: str, arguments: Mapping[str, Any]) -> Any:
        """Ruft ein Werkzeug auf und gibt sein Ergebnis zurück (siehe `tool_value`). Ohne Adresse:
        `NotConfigured` (der Vault kann dann auf den lokalen Ordner ausweichen)."""
        if not self.url:
            raise NotConfigured(self.service, _t("keine MCP-Adresse eingetragen"),
                                hint=_t("obsidian.mcp_url in den Einstellungen des Moduls Obsidian-Vault eintragen"))
        if not self._initialized:
            self._initialize()
        params = {"name": name, "arguments": dict(arguments)}
        had_session = self._session is not None
        _response, message = self._rpc("tools/call", params)
        if message is None:
            if not had_session:
                raise UpstreamError(self.service, _t("Nicht gefunden: {url}", url=self.url))
            self._initialized = False
            self._initialize()
            _response, message = self._rpc("tools/call", params)
            if message is None:
                raise UpstreamError(self.service, _t("MCP-Sitzung abgelaufen, erneuter Versuch gescheitert"))
        return self.tool_value(message.get("result") or {})

    def tool_value(self, result: Mapping[str, Any]) -> Any:
        """`structuredContent.result`, sonst `structuredContent`, sonst die Textteile von `content`."""
        texts = [str(part.get("text", "")) for part in result.get("content") or []
                 if isinstance(part, dict) and part.get("type") == "text"]
        if result.get("isError"):
            raise UpstreamError(self.service, "\n".join(texts).strip() or _t("Werkzeug meldet einen Fehler"))
        structured = result.get("structuredContent")
        if isinstance(structured, dict) and "result" in structured:
            return structured["result"]
        if structured is not None:
            return structured
        return "\n".join(texts)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "McpClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
