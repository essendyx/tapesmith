"""USB-Erkennung und -Transport (experimentell): nur Fakes, kein echtes Öffnen."""

import pytest

from tapesmith.device.profile import load_profile
from tapesmith.doctor import Check
from tapesmith.printer import PrinterSession
from tapesmith.transport.base import ConnectTimeout, TransportError
from tapesmith.transport.usb import (
    UsbDevice,
    UsbPrintTransport,
    diagnose_usb,
    find_usb_devices,
    usb_check,
)


class NullLock:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeHandle:
    def __init__(self, reply=b"\x1a\x04\x4b"):
        self.written: list[bytes] = []
        self.closed = False
        self.reply = reply

    def write(self, data):
        self.written.append(bytes(data))

    def read(self, timeout):
        return self.reply

    def close(self):
        self.closed = True


def test_find_usb_devices_and_diagnose_usbprint():
    rows = [{"instance": "USB\\VID_4C4A&PID_4155\\1", "service": "usbprint",
             "friendly_name": "P12", "class": "USBDevice"}]
    devices = find_usb_devices(reader=lambda: rows)
    assert devices == [UsbDevice("USB\\VID_4C4A&PID_4155\\1", "usbprint", "P12", "USBDevice", None)]
    lines = diagnose_usb(devices)
    assert len(lines) == 1
    assert "usbprint" in lines[0] and "Druckerschnittstelle" in lines[0] and "experimentell" in lines[0]


def test_diagnose_usb_cdc_hid_unknown_and_empty():
    cdc = UsbDevice("i1", "usbser", None, "Ports", None)
    hid = UsbDevice("i2", "HidUsb", None, "HIDClass", None)
    other = UsbDevice("i3", "usbccgp", None, "USBDevice", None)
    lines = diagnose_usb([cdc, hid, other])
    assert "virtueller COM-Port" in lines[0]
    assert "HID-Gerät" in lines[1]
    assert "unbekannt" in lines[2]
    assert diagnose_usb([]) == ["Kein P12 per USB bekannt, per USB-Kabel anstecken und einschalten"]


def test_usb_check_is_always_ok():
    check = usb_check(reader=lambda: [])
    assert isinstance(check, Check)
    assert check.ok is True
    assert "Kein P12" in check.detail


def test_usbprint_transport_no_device_raises_connect_timeout():
    t = UsbPrintTransport(enumerator=lambda: [])
    with pytest.raises(ConnectTimeout, match="usbprint"):
        t.open()


def test_usbprint_transport_with_fake_opener_roundtrip():
    handle = FakeHandle()
    t = UsbPrintTransport(opener=lambda path: handle,
                          enumerator=lambda: ["\\\\?\\usb#vid_4c4a&pid_4155#1"])
    t.open()
    assert t.name.startswith("usb:")
    t.write(b"\x1f\x11\x08")
    assert handle.written == [b"\x1f\x11\x08"]
    assert t.read(0.5) == b"\x1a\x04\x4b"
    t.close()
    assert handle.closed is True


def test_usbprint_transport_write_read_after_close_fail():
    t = UsbPrintTransport(path="usb-path", opener=lambda path: FakeHandle())
    with pytest.raises(TransportError, match="nicht geöffnet"):
        t.write(b"x")
    with pytest.raises(TransportError, match="nicht geöffnet"):
        t.read(0.1)


def test_usbprint_transport_works_with_printer_session_handshake():
    profile = load_profile()
    handle = FakeHandle()
    t = UsbPrintTransport(path="\\\\?\\usb#vid_4c4a&pid_4155#1", opener=lambda path: handle)

    session = PrinterSession(t, profile, lock=NullLock(), sleep=lambda s: None)
    with session:
        results = session.handshake()
    assert results
    assert all(resp == b"\x1a\x04\x4b" for _, resp in results)
