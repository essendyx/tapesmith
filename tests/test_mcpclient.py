"""Minimaler MCP-Client (Streamable HTTP) über httpx. Nie echtes Netz."""

import json

import httpx
import pytest

from homelab_fakes import connect_error_transport
from obsidian_fakes import MCP_URL, FakeMcp, data_json, data_text
from tapesmith.integrations import mcpclient
from tapesmith.integrations.errors import NotReachable, UpstreamError, exit_code
from tapesmith.integrations.mcpclient import McpClient


def test_initialize_session_and_headers():
    fake = FakeMcp({"vault_read": "Inhalt"})
    with McpClient(MCP_URL, transport=fake.transport()) as client:
        assert client.call_tool("vault_read", {"path": "Hosts/x"}) == "Inhalt"
        assert client.call_tool("vault_read", {"path": "Hosts/y"}) == "Inhalt"
    assert fake.methods == ["initialize", "notifications/initialized", "tools/call", "tools/call"]
    init = fake.requests[0]
    assert init["jsonrpc"] == "2.0" and init["id"] == 1
    assert init["params"]["protocolVersion"] == mcpclient.PROTOCOL_VERSION
    assert init["params"]["capabilities"] == {}
    assert init["params"]["clientInfo"]["name"] == "tapesmith"
    assert "id" not in fake.requests[1]
    ids = [r["id"] for r in fake.requests if "id" in r]
    assert len(set(ids)) == len(ids)
    assert "mcp-session-id" not in fake.headers[0]
    for headers in fake.headers:
        assert headers["accept"] == "application/json, text/event-stream"
        assert headers["content-type"] == "application/json"
    for headers in fake.headers[1:]:
        assert headers["mcp-session-id"] == "sitzung-1-1"
        assert headers["mcp-protocol-version"] == "2025-06-18"
    assert fake.requests[2]["params"] == {"name": "vault_read", "arguments": {"path": "Hosts/x"}}


def test_without_session_header():
    fake = FakeMcp({"vault_read": "x"}, session=None)
    with McpClient(MCP_URL, transport=fake.transport()) as client:
        assert client.call_tool("vault_read", {"path": "a"}) == "x"
    assert all("mcp-session-id" not in h for h in fake.headers)


def test_negotiated_protocol_version_is_used():
    fake = FakeMcp({"t": "x"}, protocol="2025-03-26")
    with McpClient(MCP_URL, transport=fake.transport()) as client:
        client.call_tool("t", {})
    assert fake.headers[-1]["mcp-protocol-version"] == "2025-03-26"


def _scripted(responses: dict):
    """Transport mit festen Antworten je Methode (für Dateien aus tests/data/obsidian)."""
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        message = json.loads(request.content)
        seen.append(message)
        method = message.get("method")
        if method == "initialize":
            return httpx.Response(200, json=data_json("mcp-initialize.json"),
                                  headers={"Mcp-Session-Id": "abc"})
        if method == "notifications/initialized":
            return httpx.Response(202)
        return responses[method](message)

    return httpx.MockTransport(handler), seen


def _json_file(name):
    def reply(message):
        body = data_json(name)
        body["id"] = message["id"]
        return httpx.Response(200, json=body)
    return reply


def _sse_file(name):
    def reply(message):
        text = data_text(name).replace('"id": 2', f'"id": {message["id"]}')
        return httpx.Response(200, content=text.encode("utf-8"),
                              headers={"Content-Type": "text/event-stream; charset=utf-8"})
    return reply


def test_json_and_sse_give_same_result():
    fake_json = FakeMcp({"vault_read": data_text("pmx30.md")})
    fake_sse = FakeMcp({"vault_read": data_text("pmx30.md")}, sse=True)
    with McpClient(MCP_URL, transport=fake_json.transport()) as a, \
            McpClient(MCP_URL, transport=fake_sse.transport()) as b:
        assert a.call_tool("vault_read", {"path": "p"}) == b.call_tool("vault_read", {"path": "p"})


def test_sse_with_notification_before_result():
    transport, _seen = _scripted({"tools/call": _sse_file("mcp-read-sse.txt")})
    with McpClient(MCP_URL, transport=transport) as client:
        text = client.call_tool("vault_read", {"path": "Hosts/pmx30"})
    assert text == data_text("pmx30.md")


def test_structured_content_result_key():
    transport, _seen = _scripted({"tools/call": _json_file("mcp-list-result.json")})
    with McpClient(MCP_URL, transport=transport) as client:
        assert client.call_tool("vault_list", {"folder": "Hosts"}) == ["Hosts/pmx30.md", "Hosts/pmx31.md"]


def test_structured_content_without_result_key():
    fake = FakeMcp({"t": {"content": [{"type": "text", "text": "x"}],
                          "structuredContent": {"a": 1}, "isError": False}})
    with McpClient(MCP_URL, transport=fake.transport()) as client:
        assert client.call_tool("t", {}) == {"a": 1}


def test_text_parts_joined():
    fake = FakeMcp({"t": {"content": [{"type": "text", "text": "a"}, {"type": "image", "data": "x"},
                                      {"type": "text", "text": "b"}]}})
    with McpClient(MCP_URL, transport=fake.transport()) as client:
        assert client.call_tool("t", {}) == "a\nb"


def test_is_error_raises_upstream_with_text():
    transport, _seen = _scripted({"tools/call": _json_file("mcp-error.json")})
    with McpClient(MCP_URL, transport=transport) as client:
        with pytest.raises(UpstreamError) as info:
            client.call_tool("vault_read", {"path": "Hosts/gibtsnicht"})
    assert "Notiz nicht gefunden: Hosts/gibtsnicht" in str(info.value)
    assert str(info.value).startswith("Obsidian: ")


def test_jsonrpc_error_has_code():
    fake = FakeMcp({})
    with McpClient(MCP_URL, transport=fake.transport()) as client:
        with pytest.raises(UpstreamError) as info:
            client.call_tool("gibtsnicht", {})
    assert "MCP-Fehler -32602: Unknown tool: gibtsnicht" in str(info.value)


def test_missing_result_is_upstream_error():
    def reply(message):
        body = "event: message\ndata: " + json.dumps({"jsonrpc": "2.0", "method": "x"}) + "\n\n"
        return httpx.Response(200, content=body.encode(), headers={"Content-Type": "text/event-stream"})

    transport, _seen = _scripted({"tools/call": reply})
    with McpClient(MCP_URL, transport=transport) as client:
        with pytest.raises(UpstreamError, match="MCP-Antwort ohne Ergebnis"):
            client.call_tool("t", {})


def test_unreadable_json_is_upstream_error():
    transport, _seen = _scripted({"tools/call": lambda m: httpx.Response(200, text="kein json",
                                                                          headers={"Content-Type": "application/json"})})
    with McpClient(MCP_URL, transport=transport) as client:
        with pytest.raises(UpstreamError):
            client.call_tool("t", {})


def test_404_with_session_reinitializes_once():
    fake = FakeMcp({"t": "ok"})
    with McpClient(MCP_URL, transport=fake.transport()) as client:
        assert client.call_tool("t", {}) == "ok"
        fake.expire_next_call = True
        assert client.call_tool("t", {}) == "ok"
    assert fake.methods == ["initialize", "notifications/initialized", "tools/call",
                            "tools/call", "initialize", "notifications/initialized", "tools/call"]
    assert fake.headers[-1]["mcp-session-id"] == "sitzung-1-2"


def test_404_twice_gives_error():
    def always_404(request):
        message = json.loads(request.content)
        if message.get("method") == "initialize":
            return httpx.Response(200, json=data_json("mcp-initialize.json"), headers={"Mcp-Session-Id": "s"})
        if message.get("method") == "notifications/initialized":
            return httpx.Response(202)
        return httpx.Response(404)

    with McpClient(MCP_URL, transport=httpx.MockTransport(always_404)) as client:
        with pytest.raises(UpstreamError):
            client.call_tool("t", {})


def test_http_error_maps_to_upstream():
    transport = httpx.MockTransport(lambda r: httpx.Response(500, text="kaputt"))
    with McpClient(MCP_URL, transport=transport) as client:
        with pytest.raises(UpstreamError, match="HTTP 500"):
            client.call_tool("t", {})


def test_connect_error_is_not_reachable_exit_5():
    with McpClient(MCP_URL, transport=connect_error_transport()) as client:
        with pytest.raises(NotReachable) as info:
            client.call_tool("t", {})
    assert exit_code(info.value) == 5
    assert "Obsidian" in str(info.value)


def test_ohne_adresse_nicht_eingerichtet_statt_absturz():
    """Ohne `obsidian.mcp_url` meldet der Client „nicht eingerichtet“ (424) statt eines internen Fehlers."""
    from tapesmith.integrations.errors import NotConfigured
    from tapesmith.integrations.mcpclient import McpClient

    client = McpClient(None, service="Obsidian")  # type: ignore[arg-type]
    with pytest.raises(NotConfigured) as info:
        client.call_tool("vault_list", {"folder": ""})
    assert "obsidian.mcp_url" in info.value.hint
