"""Tests für `tapesmith mcp` (stdio-Server für Claude Code) und `tapesmith mcp --config`."""

from __future__ import annotations

import sys

from tapesmith import cli
from tapesmith import config as config_mod
from tapesmith.mcpserver import server


def test_mcp_config_zeigt_einrichtung(capsys):
    assert cli.main(["mcp", "--config"]) == 0
    out = capsys.readouterr().out
    assert "claude mcp add tapesmith" in out
    assert "-m tapesmith.cli mcp" in out
    assert sys.executable in out
    assert "--transport http tapesmith-http http://127.0.0.1:8712/mcp" in out
    assert "Bearer <TOKEN>" in out
    assert "tapesmith token add Claude --rolle drucken" in out
    assert "p12_" not in out


def test_mcp_config_ohne_http(capsys):
    config_mod.save_config({"mcp": {"http": False}, "web": {"enabled": True, "port": 9123}})
    assert cli.main(["mcp", "--config"]) == 0
    out = capsys.readouterr().out
    assert "claude mcp add tapesmith" in out
    assert "tapesmith-http" not in out
    assert "mcp.http" in out


def test_mcp_startet_stdio_ohne_ausgabe(capsys, monkeypatch):
    calls = []
    monkeypatch.setattr(server, "run_stdio", lambda *a, **kw: calls.append((a, kw)))
    assert cli.main(["mcp"]) == 0
    assert calls == [((), {})]
    captured = capsys.readouterr()
    assert captured.out == ""


def test_run_stdio_nutzt_backend_und_druckt_nie(monkeypatch):
    """`run_stdio` baut den Server mit dem übergebenen Backend und startet den stdio-Transport."""
    seen = {}

    class FakeServer:
        def run(self, transport):
            seen["transport"] = transport

    monkeypatch.setattr(server, "_setup_stdio_logging", lambda: None)
    monkeypatch.setattr(server, "build_server", lambda backend: seen.setdefault("backend", backend) and FakeServer())

    class Backend:
        closed = False

        def close(self):
            Backend.closed = True

    backend = Backend()
    server.run_stdio(backend)
    assert seen["backend"] is backend
    assert seen["transport"] == "stdio"
    assert Backend.closed
