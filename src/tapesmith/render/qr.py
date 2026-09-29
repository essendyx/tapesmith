"""QR-Code in 1 Bit mit Größenlogik und Selbsttest (Rücklesen per zxing-cpp, falls ladbar; sonst
Warnung `render.zxing.NOT_READ_WARNING` statt Fehler).

Einheitliche Lesbarkeitsregel (gilt für alle Aufrufer: `p12 text --qr`, Vorlagen über
`render_label`, `p12 qr` über `qrcontent.capacity_report`; geprüft an dieser einen Stelle):
Modul >= WARN_MODULE_DOTS und Selbsttest ok -> ok (evtl. Warnung ab Version 3). Modul
< WARN_MODULE_DOTS -> Warnung. Modul < MIN_MODULE_DOTS oder Selbsttest fehlgeschlagen ->
Ablehnung (`unreadable_error`).
"""

from dataclasses import dataclass

import segno
from PIL import Image, ImageFilter

from tapesmith.render import zxing
from tapesmith.i18n import _t

QUIET_MODULES = 4
WARN_MODULE_DOTS = 3
MIN_MODULE_DOTS = 2


@dataclass(frozen=True)
class QrResult:
    image: Image.Image
    version: int
    error: str
    module_dots: int
    decodes: bool
    warnings: tuple[str, ...]


def unreadable_error(version: int | str, module: int | str) -> ValueError:
    return ValueError(
        _t("QR-Inhalt passt nicht lesbar auf das Band (Version {version}, Modul {module} Punkte), kürzer fassen oder Kurz-Link verwenden", version=version, module=module)
    )


def self_test(image: Image.Image, data: str, module_dots: int) -> bool | None:
    """Liest den Code mit Ruhezone zurück: einmal exakt, einmal mit leichtem Punktzuwachs (Thermodruck).
    None, wenn der Decoder fehlt (nicht rückgelesen)."""
    if not zxing.available():
        return None
    zx = zxing.require()
    quiet = QUIET_MODULES * max(module_dots, 1)
    canvas = Image.new("L", (image.width + 2 * quiet, image.height + 2 * quiet), 255)
    canvas.paste(image.convert("L"), (quiet, quiet))
    grown = canvas.resize((canvas.width * 2, canvas.height * 2), Image.NEAREST).filter(ImageFilter.MinFilter(3))
    for variant in (canvas, grown):
        if not any(r.text == data for r in zx.read_barcodes(variant)):
            return False
    return True


def render_qr(data: str, max_dots: int, error: str = "m") -> QrResult:
    qr = segno.make_qr(data, error=error, boost_error=False)
    matrix = qr.matrix
    n = len(matrix)
    module = max_dots // n
    if module < MIN_MODULE_DOTS:
        raise unreadable_error(qr.version, module)
    image = Image.new("1", (n * module, n * module), 255)
    for y, row in enumerate(matrix):
        for x, value in enumerate(row):
            if value:
                image.paste(0, (x * module, y * module, (x + 1) * module, (y + 1) * module))
    notes = []
    if module < WARN_MODULE_DOTS:
        notes.append(_t("QR-Modul nur {module} Punkte (< {warn_module_dots}), eventuell nicht scanbar", module=module, warn_module_dots=WARN_MODULE_DOTS))
    if qr.version >= 3:
        notes.append(_t("QR Version {version}: kaum Ruhezone quer zum Band, nur auf hellem Band verwenden", version=qr.version))
    verified = self_test(image, data, module)
    if verified is False:
        raise unreadable_error(qr.version, module)
    if verified is None:
        notes.append(_t(zxing.NOT_READ_WARNING))
    return QrResult(image, int(qr.version), qr.error, module, bool(verified), tuple(notes))
