"""Fake-MCP-Server für die Tests des Obsidian-Vaults. Nie echtes Netz: alles läuft über
`httpx.MockTransport`, Antworten sind erfunden bzw. aus `tests/data/obsidian/`."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import httpx

DATA = Path(__file__).parent / "data" / "obsidian"
MCP_URL = "http://mcp.test/mcp"


def data_text(name: str) -> str:
    return (DATA / name).read_text(encoding="utf-8")


def data_json(name: str) -> dict:
    return json.loads(data_text(name))


def tool_result(value: Any, *, is_error: bool = False) -> dict:
    """Werkzeug-Ergebnis wie ein FastMCP-Server: Text als `content`, sonst zusätzlich `structuredContent`."""
    if isinstance(value, str):
        return {"content": [{"type": "text", "text": value}], "isError": is_error}
    return {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}],
            "structuredContent": {"result": value}, "isError": is_error}


class FakeMcp:
    """Zustandsbehafteter Fake eines Streamable-HTTP-MCP-Servers.

    `tools`: Name -> Wert (str/list/dict) oder Callable(arguments) -> Wert bzw. vollständiges
    JSON-RPC-`result` (dict mit Schlüssel "content"). `requests` enthält alle JSON-RPC-Nachrichten,
    `headers` die Header je Nachricht."""

    def __init__(self, tools: Mapping[str, Any] | None = None, *, session: str | None = "sitzung-1",
                 sse: bool = False, protocol: str = "2025-06-18"):
        self.tools = dict(tools or {})
        self.session = session
        self.sse = sse
        self.protocol = protocol
        self.requests: list[dict] = []
        self.headers: list[httpx.Headers] = []
        self.expire_next_call = False
        self.sessions_started = 0

    # Hilfen für Tests
    @property
    def methods(self) -> list[str]:
        return [r.get("method", "") for r in self.requests]

    @property
    def tool_calls(self) -> list[tuple[str, dict]]:
        return [(r["params"]["name"], r["params"]["arguments"]) for r in self.requests
                if r.get("method") == "tools/call"]

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def _reply(self, payload: dict, extra_headers: dict | None = None) -> httpx.Response:
        headers = dict(extra_headers or {})
        if self.sse:
            body = "event: message\ndata: " + json.dumps(payload, ensure_ascii=False) + "\n\n"
            headers["Content-Type"] = "text/event-stream"
            return httpx.Response(200, content=body.encode("utf-8"), headers=headers)
        return httpx.Response(200, json=payload, headers=headers)

    def handle(self, request: httpx.Request) -> httpx.Response:
        message = json.loads(request.content.decode("utf-8"))
        self.requests.append(message)
        self.headers.append(request.headers)
        method = message.get("method")
        if method == "initialize":
            self.sessions_started += 1
            headers = {}
            if self.session:
                headers["Mcp-Session-Id"] = f"{self.session}-{self.sessions_started}"
            result = {"protocolVersion": self.protocol, "capabilities": {"tools": {}},
                      "serverInfo": {"name": "fake", "version": "0"}}
            return self._reply({"jsonrpc": "2.0", "id": message["id"], "result": result}, headers)
        if method == "notifications/initialized":
            return httpx.Response(202)
        if method == "tools/call":
            if self.expire_next_call:
                self.expire_next_call = False
                return httpx.Response(404, text="Session not found")
            name = message["params"]["name"]
            if name not in self.tools:
                return self._reply({"jsonrpc": "2.0", "id": message["id"],
                                    "error": {"code": -32602, "message": f"Unknown tool: {name}"}})
            value = self.tools[name]
            if callable(value):
                value = value(message["params"]["arguments"])
            result = value if isinstance(value, dict) and "content" in value else tool_result(value)
            return self._reply({"jsonrpc": "2.0", "id": message["id"], "result": result})
        return httpx.Response(400, text=f"unerwartete Methode {method}")


def vault_tools(notes: Mapping[str, str] | None = None) -> dict[str, Callable | Any]:
    """Werkzeuge eines kleinen Test-Vaults: Hosts/pmx30 und Dienste/testdienst."""
    store = dict(notes or {"Hosts/pmx30": data_text("pmx30.md"),
                           "Dienste/testdienst": data_text("dienst-mit-frontmatter.md")})

    def _list(args):
        folder = args.get("folder", "")
        return sorted(f"{p}.md" for p in store if not folder or p.startswith(folder + "/"))

    def _read(args):
        path = args["path"].removesuffix(".md")
        if path not in store:
            return tool_result(f"Notiz nicht gefunden: {path}", is_error=True)
        return store[path]

    def _append(args):
        path = args["path"].removesuffix(".md")
        store[path] = store.get(path, "") + args["content"]
        return "ok"

    def _write(args):
        store[args["path"].removesuffix(".md")] = args["content"]
        return "ok"

    return {"vault_list": _list, "vault_read": _read, "vault_append": _append, "vault_write": _write,
            "vault_search": lambda args: data_json("mcp-search.json")["result"],
            "changelog_add": lambda args: "eingetragen"}
