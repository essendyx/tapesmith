import contextlib
import threading
from pathlib import Path

import pytest
from PIL import Image

from tapesmith.device.profile import load_profile
from tapesmith.lock import PrinterBusy, PrintLock
from tapesmith.pacing import estimate_print_seconds
from tapesmith.printer import PrinterSession
from tapesmith.protocol.job import Packet, build_job, job_bytes
from tapesmith.protocol.raster import place_on_head
from tapesmith.transport.base import MemoryTransport, TransportError

GOLDEN = Path(__file__).parent / "golden"


def test_pacing_estimate():
    p = load_profile()
    # 480 Zeilen = 60 mm bei 60 mm/s = 1 s, plus 1,5 s Vorschub, plus 1,5 s Puffer
    assert estimate_print_seconds(480, p) == pytest.approx(4.0)


def test_session_stream_equals_golden_and_waits():
    profile = load_profile()
    head = place_on_head(Image.open(GOLDEN / "ref_label.pbm"), profile)
    transport = MemoryTransport({bytes.fromhex("1f1107"): bytes.fromhex("1a07010203")})
    slept = []
    with PrinterSession(transport, profile, sleep=slept.append) as session:
        result = session.print_image(head)
    assert b"".join(transport.written) == (GOLDEN / "ref_stream.bin").read_bytes()
    assert transport.opened and transport.closed
    assert result.rows == head.height
    assert (bytes.fromhex("1f1107"), bytes.fromhex("1a07010203")) in result.responses
    assert slept == [pytest.approx(estimate_print_seconds(head.height, profile))]
    assert result.waited_s == slept[0]


def test_query_and_listen():
    transport = MemoryTransport({bytes.fromhex("1f1108"): bytes.fromhex("1a0450")})
    with PrinterSession(transport, load_profile()) as session:
        assert session.query("1f1108") == bytes.fromhex("1a0450")
        assert session.listen(0.1) == b""


def test_lock_blocks_second_holder_in_other_thread():
    with PrintLock():
        errors = []

        def other():
            try:
                with PrintLock():
                    pass
            except PrinterBusy as exc:
                errors.append(exc)

        t = threading.Thread(target=other)
        t.start()
        t.join()
        assert errors and "belegt" in str(errors[0])
    with PrintLock():  # danach wieder frei
        pass


def test_session_closes_transport_on_error():
    transport = MemoryTransport()
    with pytest.raises(ValueError):
        with PrinterSession(transport, load_profile()) as session:
            session.print_image(Image.new("1", (10, 1), 1))
    assert transport.closed


def test_lock_wait_failure_is_os_error():
    lock = PrintLock()
    lock._k32.WaitForSingleObject = lambda handle, timeout_ms: 0xFFFFFFFF
    with pytest.raises(OSError, match="fehlgeschlagen") as exc_info:
        with lock:
            pass
    assert not isinstance(exc_info.value, PrinterBusy)
    with PrintLock():
        pass


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


def _head(rows: int) -> Image.Image:
    head = Image.new("1", (96, rows), 255)
    for y in range(0, rows, 3):
        head.putpixel((40 + y % 40, y), 0)
    return head


def test_reads_only_after_queries():
    profile = load_profile()
    head = place_on_head(Image.open(GOLDEN / "ref_label.pbm"), profile)
    transport = RecordingTransport()
    slept = []
    with PrinterSession(transport, profile, lock=contextlib.nullcontext(), sleep=slept.append) as s:
        result = s.print_image(head)
    assert transport.reads == 6
    assert len(result.responses) == 6
    assert result.status == "ok"
    assert result.rows_sent == result.rows == head.height


def test_send_reads_only_when_awaiting():
    transport = RecordingTransport({b"\x01": b"\x99"})
    with PrinterSession(transport, load_profile(), lock=contextlib.nullcontext()) as s:
        assert s.send(Packet(b"\x01", True)) == b"\x99"
        assert s.send(Packet(b"\x01", False)) == b""
    assert transport.reads == 1


def test_raster_is_chunked_but_bytes_identical():
    profile = load_profile()
    head = _head(600)
    transport = RecordingTransport()
    slept = []
    with PrinterSession(transport, profile, lock=contextlib.nullcontext(), sleep=slept.append,
                        chunk_rows=256) as s:
        s.print_image(head)
    lengths = [len(w) for w in transport.written]
    assert lengths[7:10] == [256 * 12, 256 * 12, 88 * 12]
    assert len(transport.written) == 6 + 1 + 3 + 1
    assert b"".join(transport.written) == job_bytes(build_job(head, profile))
    assert len(slept) == 1


def test_chunk_rows_zero_sends_single_block():
    profile = load_profile()
    head = _head(600)
    transport = RecordingTransport()
    with PrinterSession(transport, profile, lock=contextlib.nullcontext(), sleep=lambda s: None,
                        chunk_rows=0) as s:
        s.print_image(head)
    assert len(transport.written) == 6 + 1 + 1 + 1
    assert len(transport.written[7]) == 600 * 12
    assert b"".join(transport.written) == job_bytes(build_job(head, profile))


def test_progress_reports_rows():
    profile = load_profile()
    calls = []
    with PrinterSession(RecordingTransport(), profile, lock=contextlib.nullcontext(),
                        sleep=lambda s: None, chunk_rows=256) as s:
        s.print_image(_head(600), on_progress=lambda a, b: calls.append((a, b)))
    assert calls == [(256, 600), (512, 600), (600, 600)]
