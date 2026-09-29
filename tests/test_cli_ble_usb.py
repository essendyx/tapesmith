"""CLI-Diagnosebefehle 'p12 ble scan' und 'p12 usb' (experimentell) sowie
doctor.run_checks(extra_checks=...)."""

import json

from tapesmith import cli
from tapesmith.cli_cmds import ble as ble_cmd
from tapesmith.cli_cmds import usb as usb_cmd
from tapesmith.doctor import run_checks
from tapesmith.transport.ble import BleDevice
from tapesmith.transport.usb import usb_check


class FakeBleBackend:
    def scan(self, timeout_s):
        self.scanned_timeout = timeout_s
        return [
            BleDevice("Mi", "11:22:33:44:55:66", -80),
            BleDevice("P12", "00:11:22:33:44:55", -60),
        ]

    def connect(self, address, timeout_s):
        pass

    def start_notify(self, char_uuid, callback):
        pass

    def write(self, char_uuid, data, response):
        pass

    def disconnect(self):
        pass


def test_ble_scan_cli_lists_devices_and_marks_p12(monkeypatch, capsys):
    monkeypatch.setattr(ble_cmd, "BACKEND_FACTORY", FakeBleBackend)
    assert cli.main(["ble", "scan", "--timeout", "0.1"]) == 0
    captured = capsys.readouterr()
    assert "00:11:22:33:44:55" in captured.out
    assert "P12" in captured.out
    assert "11:22:33:44:55:66" in captured.out
    assert "experimentell" in captured.err.lower()


def test_ble_scan_cli_json(monkeypatch, capsys):
    monkeypatch.setattr(ble_cmd, "BACKEND_FACTORY", FakeBleBackend)
    assert cli.main(["ble", "scan", "--timeout", "0.1", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert isinstance(data, list)
    assert any(d["address"] == "00:11:22:33:44:55" for d in data)


def test_ble_scan_cli_reports_when_empty(monkeypatch, capsys):
    class EmptyBackend(FakeBleBackend):
        def scan(self, timeout_s):
            return []

    monkeypatch.setattr(ble_cmd, "BACKEND_FACTORY", EmptyBackend)
    assert cli.main(["ble", "scan"]) == 0
    assert "Keine BLE-Geräte" in capsys.readouterr().out


def test_usb_cli_diagnosis(monkeypatch, capsys):
    monkeypatch.setattr(usb_cmd, "READER", lambda: [
        {"instance": "USB\\VID_4C4A&PID_4155\\1", "service": "usbprint",
         "friendly_name": "P12", "class": "USBDevice"},
    ])
    monkeypatch.setattr(usb_cmd, "ENUMERATOR", lambda: [])
    assert cli.main(["usb"]) == 0
    out = capsys.readouterr().out
    assert "usbprint" in out


def test_usb_cli_json(monkeypatch, capsys):
    monkeypatch.setattr(usb_cmd, "READER", lambda: [])
    monkeypatch.setattr(usb_cmd, "ENUMERATOR", lambda: [])
    assert cli.main(["usb", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert "Kein P12" in data["lines"][0]


def test_doctor_run_checks_with_extra_checks_appends_and_survives_exception():
    def boom():
        raise RuntimeError("kaputt")

    checks = run_checks(
        "001122334455", lambda mac: "COM4", connect=lambda p: [],
        extra_checks=[lambda: usb_check(reader=lambda: []), boom],
    )
    assert checks[-2].name == "USB (experimentell)"
    assert checks[-2].ok is True
    assert checks[-1].ok is False
    assert "kaputt" in checks[-1].detail

    checks_without_extra = run_checks("001122334455", lambda mac: "COM4", connect=lambda p: [])
    assert [c.name for c in checks_without_extra] == \
        ["Geräteprofil", "Bluetooth-Port", "Drucksperre", "Drucker antwortet"]
