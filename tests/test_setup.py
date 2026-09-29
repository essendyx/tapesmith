import json

from tapesmith import paths
from tapesmith.cli import main
from tapesmith.cli_cmds import setup as setup_cmd
from tapesmith.setup import run_setup
from tapesmith.transport import btports
from tapesmith.transport.base import ConnectTimeout, MemoryTransport, TransportError

HANDSHAKE = [
    (b"\x1f\x11\x08", b"\x1a\x08A1B2C3D4E5F6G7H"),
    (b"\x1f\x11\x07", b"\x1a\x07\x01\x00\x00"),
]

ROWS_ONE_OUTGOING = [
    ("b&1&0&000000000000_00000000", "COM3"),  # eingehend, wird ignoriert
    ("b&1&0&001122334455_C00000000", "COM4"),
]

ROWS_TWO_OUTGOING = [
    ("b&1&0&001122334455_C00000000", "COM4"),
    ("b&1&0&A4000000ABCD_C00000000", "COM5"),
]


def _probe(handshake=HANDSHAKE, calls=None):
    def probe(port):
        if calls is not None:
            calls.append(port)
        return handshake
    return probe


def test_run_setup_with_given_mac_finds_port_and_saves():
    saves = []
    result = run_setup(
        mac="001122334455", port=None, ports_reader=lambda: ROWS_TWO_OUTGOING,
        probe=_probe(), save=saves.append,
    )
    assert result.ok
    assert result.exit_code == 0
    assert result.port == "COM4"
    assert result.serial == "A1B2C3D4E5F6G7H"
    assert result.firmware == "1.0.0"
    assert saves == [{"mac": "001122334455", "transport": "auto"}]
    assert result.to_dict()["exit_code"] == 0


def test_run_setup_without_mac_and_exactly_one_outgoing_port_adopts_registry_mac():
    saves = []
    result = run_setup(
        mac=None, port=None, ports_reader=lambda: ROWS_ONE_OUTGOING,
        probe=_probe(), save=saves.append,
    )
    assert result.ok
    assert result.exit_code == 0
    assert result.port == "COM4"
    assert result.mac == "001122334455"
    assert saves == [{"mac": "001122334455", "transport": "auto"}]


def test_run_setup_two_outgoing_ports_without_mac_is_ambiguous():
    saves = []
    calls = []
    result = run_setup(
        mac=None, port=None, ports_reader=lambda: ROWS_TWO_OUTGOING,
        probe=_probe(calls=calls), save=saves.append,
    )
    assert not result.ok
    assert result.exit_code == 1
    assert "--mac" in result.steps[-1].hint
    assert saves == []
    assert calls == []


def test_run_setup_no_port_found():
    saves = []
    result = run_setup(
        mac=None, port=None, ports_reader=lambda: [],
        probe=_probe(), save=saves.append,
    )
    assert not result.ok
    assert result.exit_code == 5
    assert "koppeln" in result.steps[-1].hint
    assert saves == []


def test_run_setup_probe_raises_connect_timeout():
    saves = []

    def probe(port):
        raise ConnectTimeout("COM4: keine Verbindung nach 8 s")

    result = run_setup(
        mac="001122334455", port=None, ports_reader=lambda: ROWS_ONE_OUTGOING,
        probe=probe, save=saves.append,
    )
    assert not result.ok
    assert result.exit_code == 5
    assert "Nur ein Host" in result.steps[-1].hint
    assert saves == []


def test_run_setup_only_empty_responses():
    saves = []
    result = run_setup(
        mac="001122334455", port=None, ports_reader=lambda: ROWS_ONE_OUTGOING,
        probe=_probe(handshake=[(b"\x1f\x11\x08", b"")]), save=saves.append,
    )
    assert not result.ok
    assert result.exit_code == 5
    assert "keine Antwort" in result.steps[-1].detail
    assert saves == []


def test_run_setup_test_print_failure_keeps_saved_config():
    saves = []

    def test_print(port):
        raise TransportError("weg")

    result = run_setup(
        mac="001122334455", port=None, ports_reader=lambda: ROWS_ONE_OUTGOING,
        probe=_probe(), save=saves.append, test_print=test_print,
    )
    assert saves == [{"mac": "001122334455", "transport": "auto"}]
    assert not result.ok
    assert not result.printed
    assert result.exit_code == 5


def test_run_setup_with_given_port_skips_reader():
    saves = []

    def reader():
        raise AssertionError("ports_reader sollte nicht aufgerufen werden")

    result = run_setup(
        mac=None, port="COM9", ports_reader=reader,
        probe=_probe(), save=saves.append,
    )
    assert result.port == "COM9"
    assert result.exit_code == 0
    assert saves == [{"transport": "COM9"}]


# --- CLI-Teil ---------------------------------------------------------------

RESPONSES = {
    bytes.fromhex("1f1107"): bytes.fromhex("1a08") + b"A1B2C3D4E5F6G7H" + bytes.fromhex("1a07010000"),
}


def test_cli_setup_json_finds_port_and_writes_config(monkeypatch, app_home):
    monkeypatch.setattr(setup_cmd, "SLEEP", lambda s: None)
    monkeypatch.setattr(btports, "_read_registry", lambda: ROWS_ONE_OUTGOING)
    transport = MemoryTransport(RESPONSES)
    monkeypatch.setattr(setup_cmd, "open_transport", lambda *a, **kw: transport)

    assert main(["setup", "--json"]) == 0
    cfg = json.loads(paths.config_path().read_text(encoding="utf-8"))
    assert cfg["mac"] == "001122334455"


def test_cli_setup_test_label_prints_raster_head(monkeypatch, app_home):
    monkeypatch.setattr(setup_cmd, "SLEEP", lambda s: None)
    monkeypatch.setattr(btports, "_read_registry", lambda: ROWS_ONE_OUTGOING)
    transport = MemoryTransport(RESPONSES)
    monkeypatch.setattr(setup_cmd, "open_transport", lambda *a, **kw: transport)

    assert main(["setup", "--test-label"]) == 0
    assert any(w.startswith(bytes.fromhex("1b401d763000")) for w in transport.written)


def test_cli_setup_two_ports_without_selection_is_exit_1(monkeypatch, app_home):
    monkeypatch.setattr(setup_cmd, "SLEEP", lambda s: None)
    monkeypatch.setattr(btports, "_read_registry", lambda: ROWS_TWO_OUTGOING)

    assert main(["setup"]) == 1
    assert not paths.config_path().exists()


def test_cli_setup_no_ports_is_exit_5(monkeypatch, app_home):
    monkeypatch.setattr(setup_cmd, "SLEEP", lambda s: None)
    monkeypatch.setattr(btports, "_read_registry", lambda: [])

    assert main(["setup"]) == 5


def test_cli_setup_registered_in_help(capsys):
    try:
        main(["--help"])
    except SystemExit:
        pass
    assert "setup" in capsys.readouterr().out
