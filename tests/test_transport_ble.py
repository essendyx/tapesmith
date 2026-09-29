"""BLE-Transport (experimentell): nur Fakes, kein echter Scan/Verbindung."""

import sys
import threading
import time

import pytest

from tapesmith.device.profile import load_profile
from tapesmith.printer import PrinterSession
from tapesmith.transport import ble
from tapesmith.transport.base import ConnectTimeout, TransportError
from tapesmith.transport.ble import (
    BLE_NOTIFY,
    BLE_WRITE,
    BleDevice,
    BleTransport,
    matches,
    normalize_address,
)


class FakeBackend:
    def __init__(self, scan_result=None, connect_error=None):
        self.scan_result = list(scan_result or [])
        self.connect_error = connect_error
        self.connected: list[tuple[str, float]] = []
        self.writes: list[tuple[str, bytes, bool]] = []
        self.notify_cb = None
        self.disconnected = 0

    def scan(self, timeout_s):
        self.scan_timeout = timeout_s
        return self.scan_result

    def connect(self, address, timeout_s):
        if self.connect_error is not None:
            raise self.connect_error
        self.connected.append((address, timeout_s))

    def start_notify(self, char_uuid, callback):
        assert char_uuid == BLE_NOTIFY
        self.notify_cb = callback

    def write(self, char_uuid, data, response):
        self.writes.append((char_uuid, bytes(data), response))

    def disconnect(self):
        self.disconnected += 1


class HandshakeBackend(FakeBackend):
    """Antwortet in write() sofort per Notify (wie ein echter Drucker synchron würde)."""

    def __init__(self, responses):
        super().__init__(scan_result=[BleDevice("P12", "00:11:22:33:44:55", -60)])
        self.responses = responses

    def write(self, char_uuid, data, response):
        super().write(char_uuid, data, response)
        reply = self.responses.get(bytes(data))
        if reply and self.notify_cb:
            self.notify_cb(reply)


class NullLock:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_open_without_address_scans_and_connects_to_p12():
    backend = FakeBackend(scan_result=[
        BleDevice("Mi", "11:22:33:44:55:66", None),
        BleDevice("P12", "00:11:22:33:44:55", -60),
    ])
    t = BleTransport(backend_factory=lambda: backend)
    t.open()
    assert backend.connected == [("00:11:22:33:44:55", 10.0)]
    assert backend.notify_cb is not None
    assert t.name == "ble:00:11:22:33:44:55"


def test_open_without_match_raises_connect_timeout():
    backend = FakeBackend(scan_result=[BleDevice("Mi", "11:22:33:44:55:66", None)])
    t = BleTransport(backend_factory=lambda: backend)
    with pytest.raises(ConnectTimeout, match="Kein P12 per BLE gefunden"):
        t.open()


def test_open_connect_error_raises_transport_error():
    backend = FakeBackend(
        scan_result=[BleDevice("P12", "00:11:22:33:44:55", -60)],
        connect_error=RuntimeError("weg"),
    )
    t = BleTransport(backend_factory=lambda: backend)
    with pytest.raises(TransportError, match="00:11:22:33:44:55"):
        t.open()


def test_write_chunks_128_bytes_with_pause_between():
    backend = FakeBackend(scan_result=[BleDevice("P12", "00:11:22:33:44:55", -60)])
    sleeps: list[float] = []
    t = BleTransport(backend_factory=lambda: backend, sleep=sleeps.append)
    t.open()
    t.write(bytes(300))
    assert [len(d) for _, d, _ in backend.writes] == [128, 128, 44]
    assert all(uuid == BLE_WRITE and resp is False for uuid, _, resp in backend.writes)
    assert sleeps == [0.02, 0.02]


def test_read_collects_notify_callback_from_thread():
    backend = FakeBackend(scan_result=[BleDevice("P12", "00:11:22:33:44:55", -60)])
    t = BleTransport(backend_factory=lambda: backend)
    t.open()

    def feed():
        backend.notify_cb(bytes.fromhex("1a044b"))
        time.sleep(0.01)
        backend.notify_cb(bytes.fromhex("1a0599"))

    thread = threading.Thread(target=feed)
    thread.start()
    try:
        assert t.read(0.5) == bytes.fromhex("1a044b1a0599")
    finally:
        thread.join(2)


def test_read_without_data_returns_empty():
    backend = FakeBackend(scan_result=[BleDevice("P12", "00:11:22:33:44:55", -60)])
    t = BleTransport(backend_factory=lambda: backend)
    t.open()
    assert t.read(0.05) == b""


def test_close_is_idempotent_and_write_after_close_fails():
    backend = FakeBackend(scan_result=[BleDevice("P12", "00:11:22:33:44:55", -60)])
    t = BleTransport(backend_factory=lambda: backend)
    t.open()
    t.close()
    t.close()
    assert backend.disconnected == 1
    with pytest.raises(TransportError, match="nicht geöffnet"):
        t.write(b"x")


def test_normalize_address_variants_and_invalid():
    assert normalize_address("001122334455") == "00:11:22:33:44:55"
    assert normalize_address("00-11-22-33-44-55") == "00:11:22:33:44:55"
    assert normalize_address("00:11:22:33:44:55") == "00:11:22:33:44:55"
    with pytest.raises(ValueError):
        normalize_address("nicht-valide")


def test_matches_by_name_exact_and_startswith():
    device = BleDevice("P12 PRO", "00:11:22:33:44:55", None)
    assert matches(device, ("P12", "P12 PRO", "P12PRO"), None)
    device2 = BleDevice("P12 PRO ABC", "AA:BB:CC:DD:EE:FF", None)
    assert matches(device2, ("P12 PRO",), None)
    device3 = BleDevice("Mi", "11:22:33:44:55:66", None)
    assert not matches(device3, ("P12",), None)
    device4 = BleDevice(None, "11:22:33:44:55:66", None)
    assert not matches(device4, ("P12",), None)


def test_matches_by_address_ignores_name():
    device = BleDevice(None, "00:11:22:33:44:55", None)
    assert matches(device, ("P12",), "00:11:22:33:44:55")
    assert not matches(device, ("P12",), "AA:BB:CC:DD:EE:FF")


def test_bleak_backend_without_bleak_raises_transport_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "bleak", None)
    backend = ble.BleakBackend()
    with pytest.raises(TransportError, match="bleak"):
        backend.scan(1.0)


def test_ble_transport_works_with_printer_session_handshake():
    profile = load_profile()
    responses = {p: bytes.fromhex("1a044b") for p in profile.init_packets}
    backend = HandshakeBackend(responses)
    transport = BleTransport(backend_factory=lambda: backend, sleep=lambda s: None)

    session = PrinterSession(transport, profile, lock=NullLock(), sleep=lambda s: None)
    with session:
        results = session.handshake()
    assert results
    assert all(resp == bytes.fromhex("1a044b") for _, resp in results)
