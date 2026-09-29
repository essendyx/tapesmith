"""connect_timeout_s in `p12 setup`, unabhängig von tests/test_setup.py.

Registry-Zeilen und RESPONSES hier absichtlich dupliziert, damit dieses
Modul nicht von den Hilfen einer anderen Testdatei abhängt.
"""

from tapesmith import paths
from tapesmith.cli import main
from tapesmith.cli_cmds import setup as setup_cmd
from tapesmith.transport import btports
from tapesmith.transport.base import MemoryTransport

ROWS_ONE_OUTGOING = [
    ("b&1&0&000000000000_00000000", "COM3"),  # eingehend, wird ignoriert
    ("b&1&0&001122334455_C00000000", "COM4"),
]

RESPONSES = {
    bytes.fromhex("1f1107"): bytes.fromhex("1a08") + b"A1B2C3D4E5F6G7H" + bytes.fromhex("1a07010000"),
}


def test_cli_setup_uses_connect_timeout_s_from_config(monkeypatch, app_home):
    monkeypatch.setattr(setup_cmd, "SLEEP", lambda s: None)
    monkeypatch.setattr(btports, "_read_registry", lambda: ROWS_ONE_OUTGOING)
    paths.config_path().write_text('{"connect_timeout_s": 3}', encoding="utf-8")

    calls = []

    def fake_open_transport(port, mac, hexlog=None, **kw):
        calls.append(kw)
        return MemoryTransport(RESPONSES)

    monkeypatch.setattr(setup_cmd, "open_transport", fake_open_transport)

    assert main(["setup", "--test-label"]) == 0
    assert calls
    for kw in calls:
        assert kw["open_timeout"] == 3.0
