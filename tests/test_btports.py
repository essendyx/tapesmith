import pytest

from tapesmith.transport.base import FileTransport, HexLogTransport, TransportError
from tapesmith.transport.btports import BtPort, find_outgoing_port, list_bt_ports, parse_instance
from tapesmith.transport.resolve import open_transport
from tapesmith.transport.serial_port import SerialTransport

# echte Werte dieses Rechners (Registry BTHENUM, Stand 2026-09-26)
ROWS = [
    ("b&2e7d18cf&0&000000000000_00000000", "COM3"),
    ("b&2e7d18cf&0&001122334455_C00000000", "COM4"),
]


def reader():
    return ROWS


def test_parse_instance():
    assert parse_instance(*ROWS[1]) == BtPort("COM4", "001122334455", True)
    assert parse_instance(*ROWS[0]) == BtPort("COM3", "000000000000", False)
    assert parse_instance("kaputt", "COM9") is None


def test_list_and_find():
    assert [p.port for p in list_bt_ports(reader)] == ["COM3", "COM4"]
    assert find_outgoing_port("00:11:22:33:44:55", reader) == "COM4"
    assert find_outgoing_port("A45F981A3546", reader) is None


def test_open_transport_variants(tmp_path):
    t = open_transport("auto", "001122334455", reader=reader)
    assert isinstance(t, SerialTransport) and t.port == "COM4"
    assert open_transport("COM7", "x").port == "COM7"
    assert open_transport("com:COM8", "x").port == "COM8"
    f = open_transport(f"file:{tmp_path / 'j.bin'}", "x")
    assert isinstance(f, FileTransport)
    h = open_transport("COM7", "x", hexlog=tmp_path / "h.log")
    assert isinstance(h, HexLogTransport)


def test_open_transport_auto_without_port():
    with pytest.raises(TransportError, match="gekoppelt"):
        open_transport("auto", "A45F981A3546", reader=reader)


def test_open_transport_rejects_garbage():
    with pytest.raises(ValueError, match="Transport"):
        open_transport("usb:1", "x")
