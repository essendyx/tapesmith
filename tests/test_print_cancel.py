import contextlib
import threading
import time

import pytest
from PIL import Image

from tapesmith.device.profile import load_profile
from tapesmith.jobs import CancelToken, IncompletePrint
from tapesmith.printer import PrinterSession
from tapesmith.protocol.job import build_job, job_bytes, raster_header
from tapesmith.protocol.raster import encode_rows
from tapesmith.transport.base import MemoryTransport, TransportError

# Schreibreihenfolge: 6 Init-Pakete (1..6), Kopf (7), Rasterblöcke (8..), Vorschub (letzter)
HEADER_WRITE = 7
FIRST_BLOCK_WRITE = 8


class RecordingTransport(MemoryTransport):
    """Zählt read()-Aufrufe, kann beim n-ten write() eine TransportError werfen."""

    def __init__(self, responses=None, fail_on_write: int | None = None):
        super().__init__(responses)
        self.reads = 0
        self.writes = 0
        self.fail_on_write = fail_on_write

    def write(self, data):
        self.writes += 1
        if self.fail_on_write is not None and self.writes == self.fail_on_write:
            raise TransportError("COM4: Schreiben fehlgeschlagen: Semaphore timeout")
        super().write(data)

    def read(self, timeout):
        self.reads += 1
        return super().read(timeout)


@pytest.fixture
def profile():
    return load_profile()


def _head(rows: int) -> Image.Image:
    head = Image.new("1", (96, rows), 255)
    for y in range(rows):
        head.putpixel((20 + y % 60, y), 0)       # jede Zeile hat Inhalt
    return head


def _session(transport, profile, slept, chunk_rows=256):
    return PrinterSession(transport, profile, lock=contextlib.nullcontext(),
                          sleep=slept.append, chunk_rows=chunk_rows)


def test_cancel_before_start_sends_nothing(profile):
    transport = RecordingTransport()
    token = CancelToken()
    token.cancel()
    slept = []
    with _session(transport, profile, slept) as s:
        result = s.print_image(_head(600), cancel=token)
    assert transport.written == []
    assert result.status == "abgebrochen"
    assert result.rows == 600
    assert result.rows_sent == 0
    assert result.responses == []
    assert result.waited_s == 0.0
    assert slept == []


def test_cancel_after_init_prints_nothing(profile):
    token = CancelToken()

    class CancelOnLastInit(RecordingTransport):
        def write(self, data):
            super().write(data)
            if self.writes == 6:
                token.cancel()

    transport = CancelOnLastInit()
    slept = []
    with _session(transport, profile, slept) as s:
        result = s.print_image(_head(600), cancel=token)
    assert len(transport.written) == 6
    assert result.status == "abgebrochen"
    assert result.rows_sent == 0
    assert len(result.responses) == 6
    assert slept == []


def test_cancel_mid_raster_pads_white_and_feeds(profile):
    head = _head(600)
    transport = RecordingTransport()
    token = CancelToken()
    slept = []
    calls = []

    def progress(sent, total):
        calls.append((sent, total))
        token.cancel()

    with _session(transport, profile, slept) as s:
        result = s.print_image(head, cancel=token, on_progress=progress)
    w = transport.written
    assert w[:6] == list(profile.init_packets)
    assert w[6] == raster_header(12, 600)
    assert w[7] == encode_rows(head)[: 256 * 12]
    assert w[8] == b"\x00" * (344 * 12)
    assert w[9] == profile.feed_command
    assert len(w) == 10
    assert len(b"".join(w)) == len(job_bytes(build_job(head, profile)))
    assert calls == [(256, 600)]
    assert result.status == "abgebrochen"
    assert result.rows_sent == 256
    assert result.rows == 600
    assert len(slept) == 1


def test_connection_loss_during_raster_is_incomplete(profile):
    transport = RecordingTransport(fail_on_write=FIRST_BLOCK_WRITE + 1)
    with pytest.raises(IncompletePrint) as info:
        with _session(transport, profile, []) as s:
            s.print_image(_head(600))
    exc = info.value
    assert exc.rows_sent == 256
    assert exc.rows_total == 600
    assert isinstance(exc, TransportError)
    assert "unvollständig" in str(exc)
    assert isinstance(exc.__cause__, TransportError)
    assert transport.closed


def test_connection_loss_during_header_is_incomplete_with_zero_rows(profile):
    transport = RecordingTransport(fail_on_write=HEADER_WRITE)
    with pytest.raises(IncompletePrint) as info:
        with _session(transport, profile, []) as s:
            s.print_image(_head(600))
    assert info.value.rows_sent == 0
    assert info.value.rows_total == 600


def test_connection_loss_during_feed_is_incomplete_with_all_rows(profile):
    # 600 Zeilen / 256 -> 3 Blöcke (Writes 8, 9, 10), Vorschub = 11
    transport = RecordingTransport(fail_on_write=FIRST_BLOCK_WRITE + 3)
    with pytest.raises(IncompletePrint) as info:
        with _session(transport, profile, []) as s:
            s.print_image(_head(600))
    assert info.value.rows_sent == info.value.rows_total == 600


def test_connection_loss_during_init_is_plain_transport_error(profile):
    transport = RecordingTransport(fail_on_write=2)
    with pytest.raises(TransportError) as info:
        with _session(transport, profile, []) as s:
            s.print_image(_head(600))
    assert not isinstance(info.value, IncompletePrint)


def test_cancel_from_other_thread(profile):
    head = _head(600)

    class SlowRaster(RecordingTransport):
        def write(self, data):
            if self.writes >= HEADER_WRITE and len(data) > 100:
                time.sleep(0.02)
            super().write(data)

    transport = SlowRaster()
    token = CancelToken()
    slept = []
    timer = threading.Timer(0.03, token.cancel)
    timer.start()
    try:
        with _session(transport, profile, slept, chunk_rows=16) as s:
            result = s.print_image(head, cancel=token)
    finally:
        timer.cancel()
    assert result.status == "abgebrochen"
    assert 0 < result.rows_sent < result.rows
    assert len(b"".join(transport.written)) == len(job_bytes(build_job(head, profile)))
    assert transport.written[-1] == profile.feed_command
    assert len(slept) == 1
