import json
import sys
from pathlib import Path

from tapesmith import cli, doctor, paths
from tapesmith.lock import PrinterBusy
from tapesmith.transport import btports, usb
from tapesmith.verify import VerifyReport

GOLDEN = Path(__file__).parent / "golden"


def test_main_reconfigures_streams_and_survives_non_cp1252_text(monkeypatch):
    class FakeConsoleStream:
        def __init__(self):
            self.encoding = "cp1252"
            self.errors = "strict"
            self.written = []

        def reconfigure(self, encoding=None, errors=None):
            if encoding:
                self.encoding = encoding
            if errors:
                self.errors = errors

        def write(self, s):
            s.encode(self.encoding, self.errors)  # wirft, falls Codepage nicht passt
            self.written.append(s)

        def flush(self):
            pass

    fake_out = FakeConsoleStream()
    monkeypatch.setattr(sys, "stdout", fake_out)
    monkeypatch.setattr(btports, "_read_registry",
                        lambda: [("b&1&0&001122334455_C00000000", "COM4")])
    monkeypatch.setattr(cli, "format_checks", lambda checks, as_json=False: "日本語 テスト")

    assert cli.main(["doctor", "--no-connect"]) == 0
    assert "日本語" in "".join(fake_out.written)


def test_print_image_to_file_is_golden(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "SLEEP", lambda s: None)
    out = tmp_path / "job.bin"
    assert cli.main(["--transport", f"file:{out}", "print-image", str(GOLDEN / "ref_label.pbm")]) == 0
    assert out.read_bytes() == (GOLDEN / "ref_stream.bin").read_bytes()


def test_calibrate_edge_to_file_with_hexlog(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "SLEEP", lambda s: None)
    out, log = tmp_path / "edge.bin", tmp_path / "hex.log"
    assert cli.main(["--transport", f"file:{out}", "--hexlog", str(log), "calibrate", "edge"]) == 0
    data = out.read_bytes()
    assert data[30:40] == bytes.fromhex("1b401d763000") + (12).to_bytes(2, "little") + (960).to_bytes(2, "little")
    assert "TX 1f 11 38" in log.read_text(encoding="utf-8")


def test_print_image_too_wide_is_error(tmp_path, capsys):
    from PIL import Image
    img = tmp_path / "wide.png"
    Image.new("1", (120, 10), 0).save(img)
    assert cli.main(["--transport", f"file:{tmp_path / 'x.bin'}", "print-image", str(img)]) == 1
    # über imageinput.load_image_head (gleiche Platzierung, Meldung mit --fit-Hinweis)
    assert "zu groß" in capsys.readouterr().err


def test_unknown_transport_is_exit_1(tmp_path, capsys):
    assert cli.main(["--transport", "usb:1", "probe", "1f1108"]) == 1
    assert "Transport" in capsys.readouterr().err


def test_unreachable_printer_exit_5(capsys, monkeypatch):
    monkeypatch.setattr(btports, "_read_registry", lambda: [])
    assert cli.main(["--transport", "auto", "probe", "1f1108"]) == 5
    assert "gekoppelt" in capsys.readouterr().err


def test_ports_lists_registry(capsys, monkeypatch):
    monkeypatch.setattr(btports, "_read_registry",
                        lambda: [("b&1&0&001122334455_C00000000", "COM4")])
    assert cli.main(["ports"]) == 0
    assert "COM4  001122334455  ausgehend" in capsys.readouterr().out


def test_doctor_survives_broken_calibration_json(capsys, monkeypatch):
    monkeypatch.setattr(btports, "_read_registry", lambda: [])
    paths.calibration_path().write_text("{nicht json", encoding="utf-8")
    assert cli.main(["doctor", "--no-connect"]) == 1
    out = capsys.readouterr().out
    assert "[FEHLER]" in out and "Geräteprofil" in out


def test_ports_works_despite_broken_config_json(capsys, monkeypatch):
    monkeypatch.setattr(btports, "_read_registry",
                        lambda: [("b&1&0&001122334455_C00000000", "COM4")])
    paths.config_path().write_text("{nicht json", encoding="utf-8")
    assert cli.main(["ports"]) == 0
    assert "COM4  001122334455  ausgehend" in capsys.readouterr().out


def test_doctor_respects_transport_and_hexlog(tmp_path, capsys):
    out, log = tmp_path / "x.bin", tmp_path / "h.log"
    cli.main(["--transport", f"file:{out}", "--hexlog", str(log), "doctor"])
    assert "TX 1f 11 38" in log.read_text(encoding="utf-8")
    assert out.read_bytes()  # Init-Pakete wurden in die Datei geschrieben


def test_doctor_no_connect_json(capsys, monkeypatch):
    monkeypatch.setattr(btports, "_read_registry",
                        lambda: [("b&1&0&001122334455_C00000000", "COM4")])
    assert cli.main(["doctor", "--json", "--no-connect"]) == 0
    assert '"Bluetooth-Port"' in capsys.readouterr().out


def test_busy_printer_exit_7(tmp_path, capsys, monkeypatch):
    class BusySession:
        def __enter__(self):
            raise PrinterBusy("belegt")

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(cli, "_session", lambda args, cfg, profile: BusySession())
    assert cli.main(["--transport", f"file:{tmp_path / 'x.bin'}", "calibrate", "edge"]) == 7
    assert "belegt" in capsys.readouterr().err


def test_verify_writes_capabilities(tmp_path, capsys, monkeypatch):
    recorded = {}

    class FakeVerifier:
        def __init__(self, open_session, profile, calibration_file):
            recorded["open_session"] = open_session
            recorded["profile"] = profile
            recorded["calibration_file"] = calibration_file
            self.report = VerifyReport(firmware="1.2.3", results={"responds": True})

        def run(self):
            self.report.complete = True
            return self.report

    monkeypatch.setattr(cli, "Verifier", FakeVerifier)
    assert cli.main(["--transport", f"file:{tmp_path / 'v.bin'}", "verify"]) == 0

    out = capsys.readouterr().out
    assert "Bericht:" in out
    saved = json.loads(paths.capabilities_path().read_text(encoding="utf-8"))
    assert saved["firmware"] == "1.2.3"
    assert saved["complete"] is True

    session = recorded["open_session"](recorded["profile"])
    assert session.transport.name.startswith("file:")


def test_verify_writes_partial_report_on_transport_error(tmp_path, capsys, monkeypatch):
    from tapesmith.transport.base import TransportError

    class FailingVerifier:
        def __init__(self, open_session, profile, calibration_file):
            self.report = VerifyReport(firmware="1.2.3", results={"responds": True})

        def run(self):
            raise TransportError("weg in Schritt 2")

    monkeypatch.setattr(cli, "Verifier", FailingVerifier)
    assert cli.main(["--transport", f"file:{tmp_path / 'v.bin'}", "verify"]) == 5

    out = capsys.readouterr().out
    assert "unvollständig" in out
    saved = json.loads(paths.capabilities_path().read_text(encoding="utf-8"))
    assert saved["results"] == {"responds": True}
    assert saved["complete"] is False


def test_verify_eof_during_ask_exits_1_and_writes_report(tmp_path, capsys, monkeypatch):
    class EofVerifier:
        def __init__(self, open_session, profile, calibration_file):
            self.report = VerifyReport(firmware=None, results={"responds": True})

        def run(self):
            raise EOFError()

    monkeypatch.setattr(cli, "Verifier", EofVerifier)
    assert cli.main(["--transport", f"file:{tmp_path / 'v.bin'}", "verify"]) == 1
    assert "Abgebrochen" in capsys.readouterr().err
    saved = json.loads(paths.capabilities_path().read_text(encoding="utf-8"))
    assert saved["complete"] is False


# ---------- Rechner ohne Drucker, ohne Bluetooth und ohne USB (wie der CI-Rechner) ----------

_REAL_BT_READ = btports._read_registry        # vor der autouse-Fixture `_no_real_devices` gemerkt
_REAL_USB_READ = usb._read_usb_registry


def _registry_without_device_keys(monkeypatch, error=FileNotFoundError):
    r"""HKLM\SYSTEM\CurrentControlSet\Enum\BTHENUM und Enum\USB fehlen (oder sind gesperrt), wie
    auf einer virtuellen Maschine ohne Bluetooth und ohne je angestecktes USB-Gerät."""
    import winreg

    real_open = winreg.OpenKey

    def open_key(key, sub_key, *args, **kwargs):
        if key == winreg.HKEY_LOCAL_MACHINE and "\\enum\\" in str(sub_key).lower():
            raise error(2, "Das System kann die angegebene Datei nicht finden")
        return real_open(key, sub_key, *args, **kwargs)

    monkeypatch.setattr(winreg, "OpenKey", open_key)
    monkeypatch.setattr(btports, "_read_registry", _REAL_BT_READ)
    monkeypatch.setattr(usb, "_read_usb_registry", _REAL_USB_READ)


def test_registry_readers_without_device_keys_find_nothing(monkeypatch):
    _registry_without_device_keys(monkeypatch)
    assert btports.list_bt_ports() == []
    assert usb.find_usb_devices() == []
    assert usb.usb_check().ok is True


def test_ports_without_bluetooth_is_empty_not_a_crash(capsys, monkeypatch):
    _registry_without_device_keys(monkeypatch)
    assert cli.main(["ports"]) == 0
    assert capsys.readouterr().out == ""


def test_doctor_without_printer_reports_missing_port_with_exit_1(capsys, monkeypatch):
    """Ohne gekoppelten Drucker kann nicht gedruckt werden: Exit 1 (dokumentiert: "Fehler/
    Konfiguration"), mit verständlicher Meldung und Hinweis, ohne Absturz. USB (experimentell)
    zählt nie als Fehler."""
    _registry_without_device_keys(monkeypatch)
    assert cli.main(["doctor", "--no-connect"]) == 1
    captured = capsys.readouterr()
    assert "[FEHLER] Bluetooth-Port: kein ausgehender COM-Port" in captured.out
    assert "-> Drucker einschalten, in Windows unter Bluetooth-Geräte koppeln" in captured.out
    assert "[OK]     USB (experimentell): Kein P12 per USB bekannt" in captured.out
    assert "WinError" not in captured.out and "Traceback" not in captured.err
    failed = [line for line in captured.out.splitlines() if line.startswith("[FEHLER]")]
    assert len(failed) == 1


def test_doctor_with_unreadable_device_registry_explains_and_continues(capsys, monkeypatch):
    _registry_without_device_keys(monkeypatch, error=PermissionError)
    assert cli.main(["doctor", "--json", "--no-connect"]) == 1
    checks = {c["name"]: c for c in json.loads(capsys.readouterr().out)}
    assert checks["Bluetooth-Port"]["ok"] is False
    assert "Bluetooth-Geräte nicht lesbar" in checks["Bluetooth-Port"]["detail"]
    assert checks["USB (experimentell)"]["ok"] is True
    assert "USB-Geräteliste nicht lesbar" in checks["USB (experimentell)"]["detail"]
    assert checks["Drucksperre"]["ok"] is True
