import json

from tapesmith.doctor import Check, format_checks, run_checks
from tapesmith.lock import PrinterBusy


def test_all_ok_with_handshake():
    hs = [(bytes.fromhex("1f1107"), bytes.fromhex("1a07010203"))]
    checks = run_checks("001122334455", lambda mac: "COM4", connect=lambda port: hs)
    assert [c.name for c in checks] == ["Geräteprofil", "Bluetooth-Port", "Drucksperre", "Drucker antwortet"]
    assert all(c.ok for c in checks)
    assert "COM4" in checks[1].detail
    assert "Firmware 1.2.3" in checks[3].detail


def test_handshake_uses_device_profile_codes_lid_inverted():
    hs = [(bytes.fromhex("1f1112"), bytes.fromhex("1a0599"))]
    checks = run_checks("001122334455", lambda mac: "COM4", connect=lambda port: hs)
    detail = next(c for c in checks if c.name == "Drucker antwortet").detail
    assert "Deckel offen" in detail


def test_missing_port_skips_connect_and_hints_pairing():
    called = []
    checks = run_checks("001122334455", lambda mac: None, connect=lambda p: called.append(p))
    port = next(c for c in checks if c.name == "Bluetooth-Port")
    assert not port.ok and "koppeln" in port.hint
    assert called == []
    assert not next(c for c in checks if c.name == "Drucker antwortet").ok


def test_silent_printer_and_connect_error():
    checks = run_checks("x", lambda mac: "COM4", connect=lambda p: [(b"\x1f", b"")])
    assert not checks[-1].ok and "keine Antwort" in checks[-1].detail

    def boom(port):
        raise TimeoutError("COM4: keine Verbindung")

    checks = run_checks("x", lambda mac: "COM4", connect=boom)
    assert not checks[-1].ok and "keine Verbindung" in checks[-1].detail


def test_busy_lock():
    class Busy:
        def __enter__(self):
            raise PrinterBusy("belegt")

        def __exit__(self, *a):
            return False

    checks = run_checks("x", lambda mac: "COM4", lock_factory=Busy)
    assert not next(c for c in checks if c.name == "Drucksperre").ok


def test_format_text_and_json():
    checks = [Check("A", True, "gut"), Check("B", False, "schlecht", "reparieren")]
    text = format_checks(checks)
    assert "[OK]     A: gut" in text and "[FEHLER] B: schlecht" in text and "-> reparieren" in text
    assert json.loads(format_checks(checks, as_json=True))[1] == {
        "name": "B", "ok": False, "detail": "schlecht", "hint": "reparieren"}
