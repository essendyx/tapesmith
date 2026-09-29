import threading
import time

import pytest

from tapesmith.device.profile import load_profile
from tapesmith.transport import serial_port
from tapesmith.transport.base import ConnectTimeout, FileTransport, HexLogTransport, MemoryTransport, TransportError


def test_memory_transport_answers_last_write():
    t = MemoryTransport({b"\x1f\x11\x08": b"\x1a\x04\x50"})
    t.open()
    t.write(b"\x1f\x11\x08")
    assert t.read(0.5) == b"\x1a\x04\x50"
    assert t.read(0.5) == b""
    t.write(b"\x00")
    assert t.read(0.5) == b""
    t.close()
    assert t.written == [b"\x1f\x11\x08", b"\x00"] and t.opened and t.closed


def test_file_transport_writes_job(tmp_path):
    path = tmp_path / "job.bin"
    t = FileTransport(path)
    t.open()
    t.write(b"\x01\x02")
    t.write(b"\x03")
    assert t.read(1.0) == b""
    t.close()
    assert path.read_bytes() == b"\x01\x02\x03"
    assert t.name == f"file:{path}"


def test_supports_responses_flags():
    assert MemoryTransport().supports_responses is True
    assert FileTransport("x").supports_responses is False
    assert HexLogTransport(MemoryTransport(), "x").supports_responses is True
    assert HexLogTransport(FileTransport("x"), "x").supports_responses is False


def test_hexlog_uses_device_codes_for_rx_text(tmp_path):
    log = tmp_path / "hex.log"
    codes = load_profile().status_map()
    t = HexLogTransport(MemoryTransport({b"\x1a\x05\x99": b"\x1a\x05\x99"}), log, codes=codes)
    t.open()
    t.write(bytes.fromhex("1a0599"))
    t.read(0.5)
    t.close()
    assert "Deckel offen" in log.read_text(encoding="utf-8")


def test_hexlog_records_tx_and_rx(tmp_path):
    log = tmp_path / "hex.log"
    t = HexLogTransport(MemoryTransport({b"\x1f\x11\x07": b"\x1a\x07\x01\x02\x03"}), log)
    t.open()
    t.write(b"\x1f\x11\x07")
    assert t.read(0.5) == b"\x1a\x07\x01\x02\x03"
    t.close()
    lines = log.read_text(encoding="utf-8").splitlines()
    assert "OPEN memory" in lines[0]
    assert lines[1].endswith("TX 1f 11 07")
    assert lines[2].endswith("RX 1a 07 01 02 03  # Firmware 1.2.3")
    assert "CLOSE" in lines[3]


def test_hexlog_logs_empty_read_with_timeout(tmp_path):
    log = tmp_path / "hex.log"
    t = HexLogTransport(MemoryTransport(), log)
    t.open()
    assert t.read(0.5) == b""
    t.close()
    lines = log.read_text(encoding="utf-8").splitlines()
    assert any("RX (timeout 0.5 s)" in line for line in lines)


def test_hexlog_logs_open_failure_and_reraises(tmp_path):
    class FailingOpen:
        name = "boom"

        def open(self):
            raise TransportError("kaputt")

        def write(self, data):
            pass

        def read(self, timeout):
            return b""

        def close(self):
            pass

    log = tmp_path / "hex.log"
    t = HexLogTransport(FailingOpen(), log)
    with pytest.raises(TransportError, match="kaputt"):
        t.open()
    assert "OPEN-FEHLER boom: kaputt" in log.read_text(encoding="utf-8")


def test_hexlog_closes_inner_when_logging_fails_after_open(tmp_path):
    inner = MemoryTransport()
    log = tmp_path / "missing_dir" / "hex.log"  # Elternordner fehlt bewusst
    t = HexLogTransport(inner, log)
    with pytest.raises(OSError):
        t.open()
    assert inner.opened is True
    assert inner.closed is True


def test_serial_open_times_out(monkeypatch):
    release = threading.Event()

    def hanging_serial(*args, **kwargs):
        release.wait(5)
        raise OSError("zu spät")

    monkeypatch.setattr(serial_port.serial, "Serial", hanging_serial)
    t = serial_port.SerialTransport("COM99", open_timeout=0.2)
    start = time.monotonic()
    with pytest.raises(ConnectTimeout, match="COM99"):
        t.open()
    assert time.monotonic() - start < 1.0
    release.set()


def test_serial_late_open_is_closed(monkeypatch):
    release = threading.Event()
    close_called = []

    class FakeSerial:
        def close(self):
            close_called.append(True)

    def delayed_serial(*args, **kwargs):
        release.wait(5)
        return FakeSerial()

    monkeypatch.setattr(serial_port.serial, "Serial", delayed_serial)
    t = serial_port.SerialTransport("COM5", open_timeout=0.1)
    with pytest.raises(ConnectTimeout, match="COM5"):
        t.open()
    release.set()
    # Poll up to 2s for the close to be called
    time.sleep(0.2)
    assert close_called, "FakeSerial.close() should have been called"


def test_serial_read_write_errors_are_transport_errors(monkeypatch):
    import serial as serial_module

    class FakeSerial:
        in_waiting = 0
        timeout = 0.5

        def read(self, n):
            raise serial_module.SerialException("weg")

        def write(self, data):
            raise serial_module.SerialException("weg")

        def flush(self):
            pass

        def close(self):
            pass

    def mock_serial(*args, **kwargs):
        return FakeSerial()

    monkeypatch.setattr(serial_port.serial, "Serial", mock_serial)

    # Test read() error
    t = serial_port.SerialTransport("COM1", open_timeout=8.0)
    t.open()
    with pytest.raises(TransportError, match="COM1.*Lesen fehlgeschlagen"):
        t.read(0.1)

    # Test write() error
    with pytest.raises(TransportError, match="COM1.*Schreiben fehlgeschlagen"):
        t.write(b"x")

    # Test unopened transport
    t2 = serial_port.SerialTransport("COM5")
    with pytest.raises(TransportError, match="COM5.*nicht geöffnet"):
        t2.read(0.1)
    with pytest.raises(TransportError, match="COM5.*nicht geöffnet"):
        t2.write(b"x")
