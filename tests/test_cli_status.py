import json

from tapesmith import cli
from tapesmith.transport.base import MemoryTransport


def _patch_transport(monkeypatch, transport):
    monkeypatch.setattr(cli, "open_transport", lambda spec, mac, hexlog=None, **kw: transport)
    monkeypatch.setattr(cli, "SLEEP", lambda s: None)


def test_status_json_reports_lid_closed(monkeypatch, capsys):
    transport = MemoryTransport({
        bytes.fromhex("1f1108"): bytes.fromhex("1a044b"),
        bytes.fromhex("1f1111"): bytes.fromhex("1a0689"),
        bytes.fromhex("1f1112"): bytes.fromhex("1a0598"),
    })
    _patch_transport(monkeypatch, transport)
    assert cli.main(["status", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["values"]["lid"]["value"] == "zu"


def test_status_text_warns_on_open_lid_but_exits_ok(monkeypatch, capsys):
    transport = MemoryTransport({
        bytes.fromhex("1f1108"): bytes.fromhex("1a044b"),
        bytes.fromhex("1f1111"): bytes.fromhex("1a0689"),
        bytes.fromhex("1f1112"): bytes.fromhex("1a0599"),
    })
    _patch_transport(monkeypatch, transport)
    assert cli.main(["status"]) == 0
    captured = capsys.readouterr()
    assert "Warnung: Deckel offen" in captured.err


def test_status_with_file_transport_reports_no_answer(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "SLEEP", lambda s: None)
    assert cli.main(["--transport", f"file:{tmp_path / 'dry.bin'}", "status"]) == 0
    assert "keine Statusantwort" in capsys.readouterr().out
