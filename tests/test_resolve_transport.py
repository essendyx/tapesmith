"""open_transport: neue Angaben 'ble[:adresse]' und 'usb[:pfad]', Bestehendes unverändert."""

import pytest

from tapesmith.transport.base import FileTransport
from tapesmith.transport.ble import BleTransport
from tapesmith.transport.resolve import open_transport
from tapesmith.transport.serial_port import SerialTransport
from tapesmith.transport.usb import UsbPrintTransport

MAC = "001122334455"


class FakeBleBackend:
    def scan(self, timeout_s):
        return []

    def connect(self, address, timeout_s):
        pass

    def start_notify(self, char_uuid, callback):
        pass

    def write(self, char_uuid, data, response):
        pass

    def disconnect(self):
        pass


def test_open_transport_ble_without_address():
    t = open_transport("ble", MAC, ble_backend_factory=lambda: FakeBleBackend())
    assert isinstance(t, BleTransport)
    assert t.address is None
    assert t.name == "ble"


def test_open_transport_ble_with_address_sets_address():
    t = open_transport("ble:001122334455", MAC, ble_backend_factory=lambda: FakeBleBackend())
    assert isinstance(t, BleTransport)
    assert t.address == "00:11:22:33:44:55"


def test_open_transport_usb_without_flag_raises_value_error():
    with pytest.raises(ValueError, match="experimentell"):
        open_transport("usb", MAC)
    with pytest.raises(ValueError, match="experimentell"):
        open_transport("usb:pfad", MAC)


def test_open_transport_usb_with_flag_and_path_returns_transport():
    t = open_transport("usb:\\\\?\\usb#vid_4c4a&pid_4155#1", MAC,
                       experimental={"usb"}, usb_opener=lambda path: object())
    assert isinstance(t, UsbPrintTransport)
    assert t.path == "\\\\?\\usb#vid_4c4a&pid_4155#1"


def test_open_transport_unknown_mentions_ble_and_usb():
    with pytest.raises(ValueError, match=r"ble\[:adresse\], usb\[:pfad\]"):
        open_transport("xyz", MAC)


def test_open_transport_existing_specs_unchanged(tmp_path):
    t = open_transport(f"file:{tmp_path / 'x.bin'}", MAC)
    assert isinstance(t, FileTransport)
    t2 = open_transport("COM4", MAC)
    assert isinstance(t2, SerialTransport)
    assert t2.port == "COM4"
    with pytest.raises(ValueError, match="Unbekannter Transport"):
        open_transport("nope", MAC)
