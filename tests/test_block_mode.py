"""Tests für die Blockübertragung (experimentell, standardmäßig aus) und `prelude`."""

import contextlib
import dataclasses

import pytest
from PIL import Image

from tapesmith.device.profile import load_profile
from tapesmith.jobs import CancelToken, IncompletePrint
from tapesmith.printer import PrinterSession
from tapesmith.protocol.job import build_job, job_bytes
from tapesmith.transport.base import MemoryTransport, TransportError

INIT_LEN = 6  # Anzahl Init-Pakete im P12-Profil


def _head(rows: int) -> Image.Image:
    profile = load_profile()
    return Image.new("1", (profile.head_dots, rows), 255)


class RecordingTransport(MemoryTransport):
    def __init__(self, responses=None, fail_on_write: int | None = None):
        super().__init__(responses)
        self.writes = 0
        self.fail_on_write = fail_on_write

    def write(self, data):
        self.writes += 1
        if self.fail_on_write is not None and self.writes == self.fail_on_write:
            raise TransportError("Verbindung verloren")
        super().write(data)


# 1
def test_block_rows_zero_is_byte_identical_to_before():
    profile = load_profile()
    head = _head(250)
    transport = RecordingTransport()
    with PrinterSession(transport, profile, lock=contextlib.nullcontext(), sleep=lambda s: None) as s:
        s.print_image(head)
    assert b"".join(transport.written) == job_bytes(build_job(head, profile))


# 2
def test_block_mode_splits_into_blocks_with_own_headers():
    profile = dataclasses.replace(load_profile(), block_rows=100)
    head = _head(250)
    transport = RecordingTransport()
    progress = []
    with PrinterSession(transport, profile, lock=contextlib.nullcontext(), sleep=lambda s: None) as s:
        s.print_image(head, on_progress=lambda a, b: progress.append((a, b)))
    written = transport.written[INIT_LEN:]
    assert written[0] == bytes.fromhex("1b401d763000") + b"\x0c\x00" + b"\x64\x00" + b"\x00" * 1200
    assert written[1] == bytes.fromhex("1d763000") + b"\x0c\x00" + b"\x64\x00" + b"\x00" * 1200
    assert written[2] == bytes.fromhex("1d763000") + b"\x0c\x00" + b"\x32\x00" + b"\x00" * 600
    assert written[3] == profile.feed_command
    assert len(written) == 4
    assert progress == [(100, 250), (200, 250), (250, 250)]


# 3
def test_block_mode_cancel_between_blocks_no_white_fill():
    profile = dataclasses.replace(load_profile(), block_rows=100)
    head = _head(250)
    transport = RecordingTransport()
    token = CancelToken()

    def on_progress(done, total):
        if done == 100:
            token.cancel()

    with PrinterSession(transport, profile, lock=contextlib.nullcontext(), sleep=lambda s: None) as s:
        result = s.print_image(head, cancel=token, on_progress=on_progress)

    written = transport.written[INIT_LEN:]
    assert len(written) == 2  # nur der erste Block + Vorschub, kein zweiter Block, keine Auffüllung
    assert written[-1] == profile.feed_command
    assert result.status == "abgebrochen"
    assert result.rows_sent == 100


# 4
def test_block_mode_transport_error_on_second_block_raises_incomplete():
    profile = dataclasses.replace(load_profile(), block_rows=100)
    head = _head(250)
    transport = RecordingTransport(fail_on_write=INIT_LEN + 2)  # zweiter Block schlägt fehl
    with PrinterSession(transport, profile, lock=contextlib.nullcontext(), sleep=lambda s: None) as s:
        with pytest.raises(IncompletePrint) as exc_info:
            s.print_image(head)
    assert exc_info.value.rows_sent == 100
    assert exc_info.value.rows_total == 250


# 5
def test_prelude_appears_between_last_init_packet_and_raster_header():
    profile = load_profile()
    head = _head(50)
    prelude = bytes.fromhex("1b4e0408")
    transport = RecordingTransport()
    with PrinterSession(transport, profile, lock=contextlib.nullcontext(), sleep=lambda s: None) as s:
        s.print_image(head, prelude=prelude)
    assert transport.written[INIT_LEN] == prelude
    assert transport.written[INIT_LEN + 1].startswith(bytes.fromhex("1b401d763000"))

    transport2 = RecordingTransport()
    with PrinterSession(transport2, profile, lock=contextlib.nullcontext(), sleep=lambda s: None) as s:
        s.print_image(head)
    assert b"".join(transport2.written) == job_bytes(build_job(head, profile))
