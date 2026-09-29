"""Paketfolge eines Druckjobs (P12-Protokoll, byte-kompatibel zu soburi phomemo-p12-tools)."""

from dataclasses import dataclass

from PIL import Image

from tapesmith.device.profile import DeviceProfile
from tapesmith.protocol.raster import encode_rows
from tapesmith.i18n import _t

ESC_AT_GS_V0 = bytes.fromhex("1b401d763000")
GS_V0 = bytes.fromhex("1d763000")


@dataclass(frozen=True)
class Packet:
    data: bytes
    await_response: bool


def raster_header(bytes_per_line: int, rows: int) -> bytes:
    if not 0 < rows <= 0xFFFF:
        raise ValueError(_t("Zeilenzahl {rows} außerhalb 1..65535", rows=rows))
    return ESC_AT_GS_V0 + bytes_per_line.to_bytes(2, "little") + rows.to_bytes(2, "little")


def job_parts(head: Image.Image, profile: DeviceProfile) -> tuple[list[Packet], bytes, bytes, bytes]:
    """Zerlegt den Job in (Init-Pakete, Rasterkopf, Raster, Vorschub).

    Nur die Init-/Statuspakete erwarten eine Antwort; auf Rasterkopf, Raster und
    Vorschub antwortet der P12 nicht (am Gerät belegt).
    """
    if head.width != profile.head_dots:
        raise ValueError(_t("Bild ist {width} Punkte breit, Kopf hat {head_dots}", width=head.width, head_dots=profile.head_dots))
    init = [Packet(p, True) for p in profile.init_packets]
    header = raster_header(profile.bytes_per_line, head.height)
    return init, header, encode_rows(head), profile.feed_command


def build_job(head: Image.Image, profile: DeviceProfile) -> list[Packet]:
    init, header, raster, feed = job_parts(head, profile)
    return [*init, Packet(header, False), Packet(raster, False), Packet(feed, False)]


def job_bytes(packets: list[Packet]) -> bytes:
    return b"".join(p.data for p in packets)


def block_header(bytes_per_line: int, rows: int, *, first: bool) -> bytes:
    """Kopf für einen Block der Blockübertragung: der erste Block bekommt zusätzlich ESC @."""
    if first:
        return raster_header(bytes_per_line, rows)
    if not 0 < rows <= 0xFFFF:
        raise ValueError(_t("Zeilenzahl {rows} außerhalb 1..65535", rows=rows))
    return GS_V0 + bytes_per_line.to_bytes(2, "little") + rows.to_bytes(2, "little")


def block_packets(head: Image.Image, profile: DeviceProfile) -> list[tuple[bytes, int]]:
    """Zerlegt das Kopfbild in Blöcke zu höchstens `profile.block_rows` Zeilen (experimentell).

    Jeder Block trägt Kopf + Daten in einem Stück; der letzte Block ist ggf. kürzer.
    """
    if profile.block_rows == 0:
        raise ValueError(_t("Blockmodus ist aus"))
    if head.width != profile.head_dots:
        raise ValueError(_t("Bild ist {width} Punkte breit, Kopf hat {head_dots}", width=head.width, head_dots=profile.head_dots))
    bpl = profile.bytes_per_line
    raster = encode_rows(head)
    rows_total = head.height
    block_rows = profile.block_rows
    packets: list[tuple[bytes, int]] = []
    for i, start in enumerate(range(0, rows_total, block_rows)):
        rows = min(block_rows, rows_total - start)
        data = raster[start * bpl:(start + rows) * bpl]
        header = block_header(bpl, rows, first=(i == 0))
        packets.append((header + data, rows))
    return packets
