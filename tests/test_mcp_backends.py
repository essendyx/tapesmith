"""Tests für `tapesmith.mcpserver.backends` (Fassade und HTTP, keine echte Verbindung)."""

from __future__ import annotations

import json

import httpx
import pytest

from automation_fakes import FakeFacade
from tapesmith.mcpserver.backends import FacadeBackend, HttpBackend, McpToolError
from tapesmith.webapi.labels import LabelNotPrintable, Resolved

# ---------------------------------------------------------------- Fassade


def test_facade_backend_druckt_mit_quelle_mcp():
    facade = FakeFacade()
    backend = FacadeBackend(facade)
    source = {"kind": "text", "lines": ["A"]}
    assert backend.print(source, {"copies": 1, "confirmed": True})["status"] == "ok"
    assert facade.printed == [(source, {"copies": 1, "confirmed": True}, "mcp")]
    backend.render(source, {"copies": 2})
    assert facade.rendered == [(source, {"copies": 2}, "mcp")]
    assert [t["name"] for t in backend.templates()] == ["gefriergut", "eigentum"]
    assert backend.status()["view"]["chip"].startswith("P12")
    assert backend.queue()["jobs"] == []
    assert backend.history(5, "") == []


def test_facade_backend_grenzen_aus_konfiguration():
    assert FacadeBackend(FakeFacade()).copy_limit() == 5
    backend = FacadeBackend(FakeFacade(config={"guard": {"confirm_copies": 3}}))
    assert backend.copy_limit() == 3
    assert "höchstens 3 Kopien" in backend.limits_text()


def test_facade_backend_nicht_druckbar():
    facade = FakeFacade()
    facade.raise_on_print = LabelNotPrintable(Resolved(title="", labels=(), meta=None, ok=False,
                                                       errors=["Pflichtfeld fehlt"], warnings=[], issues=[],
                                                       fixes=[]))
    with pytest.raises(McpToolError, match="Pflichtfeld fehlt"):
        FacadeBackend(facade).print({"kind": "text", "lines": ["A"]}, None)


# ---------------------------------------------------------------- HTTP


class Recorder:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []
        self.clients: list[dict] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        status, body = self.responses.pop(0)
        return httpx.Response(status, json=body)

    def factory(self, **kw) -> httpx.Client:
        self.clients.append(kw)
        return httpx.Client(transport=httpx.MockTransport(self.handler), **kw)


def _sessions(*tokens):
    items = [{"port": 18712 + i, "token": t} for i, t in enumerate(tokens)]
    calls = []

    def loader():
        calls.append(1)
        return items[min(len(calls) - 1, len(items) - 1)]

    return loader, calls


def test_http_backend_kopf_und_ziel():
    rec = Recorder([(200, {"templates": [{"name": "a"}]}), (200, {"entries": [{"id": 1}]})])
    loader, calls = _sessions("tok-1")
    backend = HttpBackend(session_loader=loader, client_factory=rec.factory, config_loader=lambda: {})
    assert backend.templates() == [{"name": "a"}]
    assert backend.history(3, "gulasch") == [{"id": 1}]
    first = rec.requests[0]
    assert str(first.url) == "http://127.0.0.1:18712/api/v1/templates"
    assert first.headers["X-P12-Token"] == "tok-1"
    assert first.headers["X-P12-Source"] == "mcp"
    assert rec.requests[1].url.params["query"] == "gulasch"
    assert rec.requests[1].url.params["limit"] == "3"
    assert calls == [1]
    assert backend.copy_limit() == 5


def test_http_backend_render_und_print_senden_quelle_und_optionen():
    rec = Recorder([(200, {"ok": True}), (200, {"status": "ok"})])
    loader, _ = _sessions("tok")
    backend = HttpBackend(session_loader=loader, client_factory=rec.factory)
    source = {"kind": "text", "lines": ["A"]}
    backend.render(source, {"copies": 2})
    backend.print(source, {"copies": 2, "confirmed": True})
    assert rec.requests[0].url.path == "/api/v1/labels/render"
    assert rec.requests[1].url.path == "/api/v1/labels/print"
    assert json.loads(rec.requests[1].content) == {"source": source, "options": {"copies": 2, "confirmed": True}}


def test_http_backend_401_laedt_sitzung_einmal_neu():
    rec = Recorder([(401, {"error": {"kind": "Unauthorized", "message": "Nicht angemeldet"}}),
                    (200, {"jobs": [], "paused": False})])
    loader, calls = _sessions("alt", "neu")
    backend = HttpBackend(session_loader=loader, client_factory=rec.factory)
    assert backend.queue() == {"jobs": [], "paused": False}
    assert len(calls) == 2
    assert rec.requests[1].headers["X-P12-Token"] == "neu"
    assert str(rec.requests[1].url).startswith("http://127.0.0.1:18713/")


def test_http_backend_zweites_401_ist_fehler():
    rec = Recorder([(401, {}), (401, {})])
    loader, calls = _sessions("a", "b")
    backend = HttpBackend(session_loader=loader, client_factory=rec.factory)
    with pytest.raises(McpToolError, match="Nicht angemeldet"):
        backend.status()
    assert len(calls) == 2
    assert len(rec.requests) == 2


def test_http_backend_label_fehler_422():
    body = {"error": {"kind": "Label", "message": "x", "hint": "", "exit_code": 1,
                      "details": {"errors": ["Pflichtfeld inhalt fehlt", "Text zu lang"], "missing_secrets": []}}}
    rec = Recorder([(422, body)])
    loader, _ = _sessions("tok")
    backend = HttpBackend(session_loader=loader, client_factory=rec.factory)
    with pytest.raises(McpToolError) as info:
        backend.print({"kind": "template", "template": "gefriergut", "values": {}}, None)
    assert "Pflichtfeld inhalt fehlt" in str(info.value)
    assert "Text zu lang" in str(info.value)


def test_http_backend_fehler_mit_hinweis():
    body = {"error": {"kind": "PrinterBusy", "message": "Drucker belegt", "hint": "später erneut",
                      "exit_code": 7, "details": None}}
    rec = Recorder([(409, body)])
    loader, _ = _sessions("tok")
    backend = HttpBackend(session_loader=loader, client_factory=rec.factory)
    with pytest.raises(McpToolError, match="Drucker belegt.*später erneut"):
        backend.status()


def test_http_backend_dienst_nicht_erreichbar():
    def boom():
        raise RuntimeError("Druckdienst startet nicht")

    backend = HttpBackend(session_loader=boom, client_factory=lambda **kw: pytest.fail("kein Client"))
    with pytest.raises(McpToolError, match="Druckdienst startet nicht"):
        backend.templates()

    def refuse(request):
        raise httpx.ConnectError("verweigert", request=request)

    loader, _ = _sessions("tok")
    backend = HttpBackend(session_loader=loader,
                          client_factory=lambda **kw: httpx.Client(transport=httpx.MockTransport(refuse), **kw))
    with pytest.raises(McpToolError, match="nicht erreichbar"):
        backend.queue()


def test_http_backend_grenzen_aus_lokaler_konfiguration():
    backend = HttpBackend(session_loader=lambda: {}, config_loader=lambda: {"guard": {"confirm_copies": 2}})
    assert backend.copy_limit() == 2

    def broken():
        raise ValueError("kaputt")

    assert HttpBackend(session_loader=lambda: {}, config_loader=broken).copy_limit() == 5
