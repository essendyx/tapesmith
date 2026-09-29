"""Dichte-Kalibrierassistent (experimentell): Teststreifen je Kandidatenbefehl.

Für den P12 ist kein Dichtebefehl belegt (nur Vermutungen aus anderen phomemo-Modellen). Es wird
**nur** ein Teststreifen gedruckt (mit dem Kandidatenbefehl als `prelude`, siehe `printer.print_image`);
der gewählte Wert wird im Bandprofil gespeichert, aber nie automatisch gesendet. ESC 7
(Heizparameter) wird über die Schutzliste (`protocol.rawcmd.classify_raw`) ausdrücklich ausgeschlossen.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from PIL import Image, ImageDraw

from tapesmith.device.profile import DeviceProfile
from tapesmith.protocol.rawcmd import classify_raw
from tapesmith.render.compose import mm_to_rows
from tapesmith.render.qr import render_qr
from tapesmith.render.text import fit_text
from tapesmith.i18n import N_, _t

FAMILIES = {"m110": "1B 4E 04 n (M110)", "m02": "1F 11 02 n (M02/M04)"}
VALUE_RANGE = range(1, 16)
DEFAULT_VALUES = (3, 8, 12)
MAX_VALUES = 6
QR_GAP_DOTS = 8
TEST_QR_DATA = "P12"     # kleiner QR (Version 1) je Feld

WARNING = (N_("Experimentell: Für den P12 ist kein Dichtebefehl belegt (phomymo #45). Sicherster Weg ist der HCI-Snoop-Mitschnitt (docs/hardware/hci-snoop.md). ESC 7 (Heizparameter) wird nie gesendet."))
PRINT_MASTER_NOTE = (N_("Achtung Print-Master-Effekt: Wurde seit dem Einschalten schon einmal aus der Print-Master-App gedruckt, druckt der P12 bis zum nächsten Neustart dunkler. Für einen fairen Vergleich den Drucker vorher aus- und wieder einschalten und nicht aus Print Master drucken."))

_FAMILY_LABELS = {"m110": "M110", "m02": "M02"}


@dataclass(frozen=True)
class DensityCandidate:
    number: int        # Feldnummer 1..N
    family: str
    value: int
    command: bytes
    label: str         # z. B. "#2 M110 n=8"


def _command(family: str, value: int) -> bytes:
    if family == "m110":
        return bytes([0x1B, 0x4E, 0x04, value])
    return bytes([0x1F, 0x11, 0x02, value])


def density_candidates(family: str, values: Sequence[int] = DEFAULT_VALUES) -> list[DensityCandidate]:
    if family not in FAMILIES:
        raise ValueError(_t("Unbekannte Dichte-Familie '{family}' (erlaubt: {items})", family=family, items=', '.join(sorted(FAMILIES))))
    values = list(values)
    if len(values) > MAX_VALUES:
        raise ValueError(_t("Höchstens {max_values} Werte erlaubt, {count} angegeben", max_values=MAX_VALUES, count=len(values)))
    fam_label = _FAMILY_LABELS[family]
    candidates: list[DensityCandidate] = []
    for i, value in enumerate(values, start=1):
        if value not in VALUE_RANGE:
            raise ValueError(_t("Wert {value} außerhalb {start}..{value2}", value=value, start=VALUE_RANGE.start, value2=VALUE_RANGE.stop - 1))
        command = _command(family, value)
        verdict = classify_raw(command)
        assert verdict.level == "erlaubt", (
            f"Dichte-Kandidat {command.hex()} wäre laut Schutzliste '{verdict.level}', Schutzliste verletzt")
        candidates.append(DensityCandidate(i, family, value, command, f"#{i} {fam_label} n={value}"))
    return candidates


def density_test_head(candidate: DensityCandidate, profile: DeviceProfile, length_mm: float = 45.0) -> Image.Image:
    """Teststreifen: Beschriftung, Graufläche, feine Linien, kleiner Text, QR, der Länge
    nach hintereinander im Inhaltsbereich des Kopfbilds."""
    if length_mm < 35:
        raise ValueError(_t("Teststreifen braucht mindestens 35 mm"))
    height = mm_to_rows(length_mm, profile)
    offset = profile.content_offset
    content_w = profile.content_dots
    head = Image.new("1", (profile.head_dots, height), 255)

    qr = render_qr(TEST_QR_DATA, min(content_w, 64))
    qr_zone_h = qr.image.height + 2 * QR_GAP_DOTS
    remaining = height - qr_zone_h
    zone_h = remaining // 4
    zone_heights = [zone_h, zone_h, zone_h, remaining - 3 * zone_h]

    y = 0
    # Zone 1: Beschriftung
    label_block = fit_text([candidate.label], "mono", zone_heights[0], content_w)
    lx = offset + (content_w - label_block.image.width) // 2
    ly = y + (zone_heights[0] - label_block.image.height) // 2
    head.paste(label_block.image, (lx, ly))
    y += zone_heights[0]

    # Zone 2: Graufläche, 50-%-Schachbrett (1-Punkt-Raster)
    for row in range(zone_heights[1]):
        base_row = y + row
        for col in range(content_w):
            if (row + col) % 2 == 0:
                head.putpixel((offset + col, base_row), 0)
    y += zone_heights[1]

    # Zone 3: feine Linien, 1-Punkt-Haarlinien im Abstand 3
    draw = ImageDraw.Draw(head)
    for row in range(0, zone_heights[2], 3):
        draw.line([(offset, y + row), (offset + content_w - 1, y + row)], fill=0)
    y += zone_heights[2]

    # Zone 4: kleiner Text
    small_block = fit_text(["Abc 0O8B 123"], "mono", zone_heights[3], content_w)
    sx = offset + (content_w - small_block.image.width) // 2
    sy = y + (zone_heights[3] - small_block.image.height) // 2
    head.paste(small_block.image, (sx, sy))
    y += zone_heights[3]

    # Zone 5: QR, mit >= 8 weißen Zeilen Abstand zu Zone 4 und zum Ende
    qy = y + QR_GAP_DOTS
    qx = offset + (content_w - qr.image.width) // 2
    head.paste(qr.image, (qx, qy))

    return head
