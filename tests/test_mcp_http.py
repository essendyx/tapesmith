"""Tests für `/mcp` (Streamable HTTP im Dienst) und den In-Memory-Weg des MCP-Servers.

Echte App aus `create_app`, Fake-Dienst mit MemoryTransport; kein Port, kein Gerät.
"""

from __future__ import annotations

import json

import anyio
import pytest

from automation_fakes import FakeFacade
from daemon_fakes import FakeNow
from tapesmith import config as config_mod
from tapesmith.mcpserver.backends import FacadeBackend
from tapesmith.mcpserver.server import build_server
from webapi_fakes import TOKEN, close_ctx, make_client, make_token

MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
PROTOCOL = "2025-06-18"
TOOLS = {"list_templates", "label_preview", "label_print", "printer_status", "print_history", "queue_list"}


def _rpc(client, method: str, params: dict | None = None, *, id: int = 1, headers: dict | None = None):
    body = {"jsonrpc": "2.0", "id": id, "method": method}
    if params is not None:
        body["params"] = params
    hdrs = dict(MCP_HEADERS)
    if method != "initialize":
        hdrs["MCP-Protocol-Version"] = PROTOCOL
    hdrs.update(headers or {})
    return client.post("/mcp", json=body, headers=hdrs, follow_redirects=False)


def _initialize(client, **kw):
    return _rpc(client, "initialize", {"protocolVersion": PROTOCOL, "capabilities": {},
                                       "clientInfo": {"name": "pytest", "version": "1"}}, **kw)


def _call(client, name: str, arguments: dict, *, id: int = 2) -> dict:
    r = _rpc(client, "tools/call", {"name": name, "arguments": arguments}, id=id)
    assert r.status_code == 200, r.text
    return r.json()["result"]


def _text_json(result: dict) -> dict:
    texts = [c for c in result["content"] if c["type"] == "text"]
    return json.loads(texts[0]["text"])


@pytest.fixture
def mcp_api(tmp_path):
    client, ctx = make_client(tmp_path, now=FakeNow())
    ctx.service._debouncer._min_interval_s = 0
    with client:
        yield client, ctx
    close_ctx(ctx)


def _history(ctx) -> list:
    return ctx.history().search("", 50)


def test_initialize_ohne_weiterleitung(mcp_api):
    client, _ = mcp_api
    r = _initialize(client)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["result"]["serverInfo"]["name"] == "tapesmith"
    assert "confirm=true" in data["result"]["instructions"]
    assert r.headers["cache-control"] == "no-store"


def test_tools_list_und_vorschau_ohne_druck(mcp_api):
    client, ctx = mcp_api
    assert _initialize(client).status_code == 200
    r = _rpc(client, "tools/list", id=2)
    assert r.status_code == 200
    tools = {t["name"]: t for t in r.json()["result"]["tools"]}
    assert set(tools) == TOOLS
    confirm = tools["label_print"]["inputSchema"]["properties"]["confirm"]
    assert confirm["type"] == "boolean" and confirm["default"] is False

    result = _call(client, "label_preview", {"text": ["Hallo MCP"]}, id=3)
    assert result["isError"] is False
    assert any(c["type"] == "image" and c["mimeType"] == "image/png" for c in result["content"])
    preview = _text_json(result)
    assert preview["ok"] is True and preview["preview_id"]

    out = _text_json(_call(client, "label_print", {"preview_id": preview["preview_id"]}, id=4))
    assert out["printed"] is False
    out = _text_json(_call(client, "label_print", {"preview_id": preview["preview_id"], "confirm": False}, id=5))
    assert out["printed"] is False
    text_confirm = _call(client, "label_print", {"preview_id": preview["preview_id"], "confirm": "true"}, id=6)
    assert text_confirm["isError"] is True
    assert _history(ctx) == []
    assert not ctx.service._test_transport.written


def test_druck_mit_confirm_quelle_mcp(mcp_api):
    client, ctx = mcp_api
    preview = _text_json(_call(client, "label_preview", {"text": ["Gulasch", "2026-09-28"]}))
    out = _text_json(_call(client, "label_print", {"preview_id": preview["preview_id"], "confirm": True}, id=3))
    assert out["printed"] is True, out
    assert out["status"] == "ok"
    entries = _history(ctx)
    assert len(entries) == 1
    assert entries[0].source == "mcp"
    again = _text_json(_call(client, "label_print", {"preview_id": preview["preview_id"], "confirm": True}, id=4))
    assert again["printed"] is False
    assert len(_history(ctx)) == 1

    history = json.loads(_call(client, "print_history", {"limit": 5}, id=5)["content"][0]["text"])
    assert history[0]["source"] == "mcp"


def test_kopiengrenze_ist_tool_fehler(mcp_api):
    client, ctx = mcp_api
    result = _call(client, "label_preview", {"text": ["A"], "copies": 6})
    assert result["isError"] is True
    assert "1 bis 5" in result["content"][0]["text"]
    assert _history(ctx) == []


def test_status_und_warteschlange(mcp_api):
    client, _ = mcp_api
    status = json.loads(_call(client, "printer_status", {})["content"][0]["text"])
    assert set(status) == {"text", "state", "detail"}
    queue = json.loads(_call(client, "queue_list", {}, id=3)["content"][0]["text"])
    assert queue["jobs"] == [] and queue["paused"] is False
    templates = json.loads(_call(client, "list_templates", {"query": "gefrier"}, id=4)["content"][0]["text"])
    assert any(t["name"] == "gefriergut" for t in templates)


def test_zugriff_token_und_rollen(tmp_path):
    client, ctx = make_client(tmp_path, auth=None)
    try:
        with client:
            assert _initialize(client).status_code == 401
            family = make_token(ctx, "familie")
            assert _initialize(client, headers={"Authorization": f"Bearer {family}"}).status_code == 403
            printer = make_token(ctx, "drucken")
            r = _initialize(client, headers={"Authorization": f"Bearer {printer}"})
            assert r.status_code == 200, r.text
            assert r.json()["result"]["serverInfo"]["name"] == "tapesmith"
            admin = make_token(ctx, "admin")
            assert _initialize(client, headers={"Authorization": f"Bearer {admin}"}).status_code == 200
            assert _initialize(client, headers={"X-P12-Token": TOKEN}).status_code == 200
    finally:
        close_ctx(ctx)


def test_mcp_http_aus_ergibt_404(tmp_path):
    client, ctx = make_client(tmp_path)
    try:
        with client:
            assert _initialize(client).status_code == 200
            config_mod.save_config({"mcp": {"http": False}})
            r = _initialize(client)
            assert r.status_code == 404
            assert r.json()["error"]["kind"] == "NotFound"
    finally:
        close_ctx(ctx)


def test_get_mcp_nie_index_html(mcp_api):
    client, _ = mcp_api
    for path in ("/mcp", "/mcp/", "/mcp/x"):
        r = client.get(path, headers=MCP_HEADERS)
        assert r.status_code == 404, path
        assert "<title>P12</title>" not in r.text
        assert r.json()["error"]["kind"] == "NotFound"
    assert client.delete("/mcp").status_code == 404


def test_ohne_lifespan_kein_absturz(tmp_path):
    client, ctx = make_client(tmp_path)
    try:
        r = _initialize(client)
        assert r.status_code == 503
    finally:
        close_ctx(ctx)


# ---------------------------------------------------------------- In-Memory (ohne HTTP)


def test_in_memory_list_und_call():
    from mcp import Client

    facade = FakeFacade()
    server = build_server(FacadeBackend(facade))

    async def main():
        async with Client(server) as client:
            tools = await client.list_tools()
            names = {t.name for t in tools.tools}
            assert all("\n    " not in (t.description or "") for t in tools.tools)
            preview = await client.call_tool("label_preview", {"text": ["A"]})
            data = json.loads(preview.content[0].text)
            no = await client.call_tool("label_print", {"preview_id": data["preview_id"]})
            yes = await client.call_tool("label_print", {"preview_id": data["preview_id"], "confirm": True})
            return names, preview, json.loads(no.content[0].text), json.loads(yes.content[0].text)

    names, preview, no, yes = anyio.run(main)
    assert names == TOOLS
    assert any(c.type == "image" for c in preview.content)
    assert no["printed"] is False
    assert yes["printed"] is True
    assert len(facade.printed) == 1
    assert facade.printed[0][1]["confirmed"] is True
    assert facade.printed[0][2] == "mcp"
