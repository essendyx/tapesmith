"""Druck-Sitzung: Sperre, Verbindung, Handshake, Job, Pacing."""

import time
from collections.abc import Callable
from dataclasses import dataclass

from PIL import Image

from tapesmith.device.profile import DeviceProfile
from tapesmith.jobs import CancelToken, IncompletePrint
from tapesmith.lock import PrintLock
from tapesmith.pacing import estimate_print_seconds
from tapesmith.protocol.job import Packet, block_packets, job_parts
from tapesmith.transport.base import Transport, TransportError
from tapesmith.i18n import _t

STATUS_OK = "ok"
STATUS_CANCELLED = "abgebrochen"


@dataclass
class PrintResult:
    rows: int
    responses: list[tuple[bytes, bytes]]  # nur Pakete mit await_response
    waited_s: float
    status: str = STATUS_OK  # "ok" | "abgebrochen"
    rows_sent: int | None = None  # None -> rows

    def __post_init__(self) -> None:
        if self.rows_sent is None:
            self.rows_sent = self.rows


class PrinterSession:
    def __init__(self, transport: Transport, profile: DeviceProfile, lock=None, sleep=time.sleep,
                 chunk_rows: int = 256):
        self.transport = transport
        self.profile = profile
        self._lock = lock if lock is not None else PrintLock()
        self._sleep = sleep
        self.chunk_rows = chunk_rows

    def __enter__(self):
        self._lock.__enter__()
        try:
            self.transport.open()
        except BaseException:
            self._lock.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *exc):
        try:
            self.transport.close()
        finally:
            self._lock.__exit__(*exc)
        return False

    def exchange(self, data: bytes, timeout: float | None = None) -> bytes:
        self.transport.write(data)
        return self.transport.read(self.profile.response_timeout_s if timeout is None else timeout)

    def handshake(self) -> list[tuple[bytes, bytes]]:
        return [(p, self.exchange(p)) for p in self.profile.init_packets]

    def send(self, packet: Packet) -> bytes:
        """Schreibt ein Paket; liest nur, wenn das Paket eine Antwort erwartet."""
        if packet.await_response:
            return self.exchange(packet.data)
        self.transport.write(packet.data)
        return b""

    def print_image(self, head: Image.Image, cancel: CancelToken | None = None,
                    on_progress: Callable[[int, int], None] | None = None, *,
                    prelude: bytes = b"") -> PrintResult:
        rows = head.height

        def cancelled() -> bool:
            return cancel is not None and cancel.cancelled

        if cancelled():
            return PrintResult(rows, [], 0.0, STATUS_CANCELLED, 0)
        init = [Packet(p, True) for p in self.profile.init_packets]
        responses = [(p.data[:12], self.send(p)) for p in init]
        if cancelled():
            return PrintResult(rows, responses, 0.0, STATUS_CANCELLED, 0)

        if self.profile.block_rows > 0:
            return self._print_image_blocks(head, responses, cancel, on_progress, prelude)

        _, header, raster, feed = job_parts(head, self.profile)

        # Ab dem Rasterkopf ist der Druck angekündigt: Abbrüche der Verbindung
        # hinterlassen ein unvollständiges Etikett.
        bpl = self.profile.bytes_per_line
        chunk = self.chunk_rows * bpl if self.chunk_rows > 0 else len(raster)
        rows_sent = 0
        status = STATUS_OK
        try:
            if prelude:
                self.transport.write(prelude)
            self.transport.write(header)
            for start in range(0, len(raster), chunk):
                block = raster[start:start + chunk]
                self.transport.write(block)
                rows_sent += len(block) // bpl
                if on_progress is not None:
                    on_progress(rows_sent, rows)
                if rows_sent < rows and cancelled():
                    # Rest als Weiß: der Kopf hat die Zeilenzahl schon angekündigt.
                    self.transport.write(b"\x00" * ((rows - rows_sent) * bpl))
                    status = STATUS_CANCELLED
                    break
            self.transport.write(feed)
        except IncompletePrint:
            raise
        except TransportError as exc:
            raise IncompletePrint(
                _t("Druck unvollständig: Verbindung nach {rows_sent} von {rows} Zeilen abgebrochen ({exc})", rows_sent=rows_sent, rows=rows, exc=exc),
                rows_sent, rows,
            ) from exc

        waited = estimate_print_seconds(rows, self.profile)
        self._sleep(waited)
        return PrintResult(rows, responses, waited, status, rows_sent)

    def _print_image_blocks(self, head: Image.Image, responses: list[tuple[bytes, bytes]],
                            cancel: CancelToken | None, on_progress: Callable[[int, int], None] | None,
                            prelude: bytes) -> PrintResult:
        """Blockmodus (experimentell): Raster in Blöcken mit je eigenem Rasterkopf, ohne Weißauffüllung
        bei Abbruch (jeder Block hat seine Zeilen schon selbst angekündigt)."""
        rows = head.height

        def cancelled() -> bool:
            return cancel is not None and cancel.cancelled

        packets = block_packets(head, self.profile)
        rows_sent = 0
        status = STATUS_OK
        try:
            if prelude:
                self.transport.write(prelude)
            for data, block_rows in packets:
                self.transport.write(data)
                rows_sent += block_rows
                if on_progress is not None:
                    on_progress(rows_sent, rows)
                if rows_sent < rows and cancelled():
                    status = STATUS_CANCELLED
                    break
            self.transport.write(self.profile.feed_command)
        except IncompletePrint:
            raise
        except TransportError as exc:
            raise IncompletePrint(
                _t("Druck unvollständig: Verbindung nach {rows_sent} von {rows} Zeilen abgebrochen ({exc})", rows_sent=rows_sent, rows=rows, exc=exc),
                rows_sent, rows,
            ) from exc

        waited = estimate_print_seconds(rows_sent if status == STATUS_CANCELLED else rows, self.profile)
        self._sleep(waited)
        return PrintResult(rows, responses, waited, status, rows_sent)

    def query(self, command_hex: str) -> bytes:
        return self.exchange(bytes.fromhex(command_hex))

    def listen(self, seconds: float) -> bytes:
        deadline = time.monotonic() + seconds
        data = b""
        while (remaining := deadline - time.monotonic()) > 0:
            chunk = self.transport.read(remaining)
            if not chunk:
                break
            data += chunk
        return data
