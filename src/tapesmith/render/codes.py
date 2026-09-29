"""Gemeinsame Code-Helfer: Selbsttest per Rücklesen (wie render.qr.self_test) und
Invertierung für dunkles Band."""

from dataclasses import dataclass

from PIL import Image, ImageChops, ImageFilter

from tapesmith.render import zxing


@dataclass(frozen=True)
class CodeResult:
    image: Image.Image          # Modus "1", 0 = schwarz, ohne Ruhezone
    kind: str                   # "code128" | "datamatrix"
    module_dots: int
    quiet_dots: int              # Breite der nötigen Ruhezone in Punkten (je Seite)
    decodes: bool                # Selbsttest bestanden (False auch, wenn nicht rückgelesen)
    warnings: tuple[str, ...]


def self_test_code(image: Image.Image, data: str, fmt, quiet_dots: int) -> bool | None:
    """Liest den Code mit Ruhezone zurück: einmal exakt, einmal mit leichtem Punktzuwachs
    (Thermodruck) via 2x-Skalierung + MinFilter(3). Beide Varianten müssen den Inhalt liefern.

    `fmt` ist ein Formatname ("Code128", "DataMatrix") oder ein `zxingcpp.BarcodeFormat`.
    None, wenn der Decoder fehlt (zxing-cpp nicht ladbar): dann nicht rückgelesen."""
    if not zxing.available():
        return None
    zx = zxing.require()
    fmt = zxing.barcode_format(fmt)
    quiet = max(quiet_dots, 1)
    canvas = Image.new("L", (image.width + 2 * quiet, image.height + 2 * quiet), 255)
    canvas.paste(image.convert("L"), (quiet, quiet))
    grown = canvas.resize((canvas.width * 2, canvas.height * 2), Image.NEAREST).filter(ImageFilter.MinFilter(3))
    for variant in (canvas, grown):
        if not any(r.text == data for r in zx.read_barcodes(variant, formats=fmt)):
            return False
    return True


def invert_with_quiet(
    image: Image.Image, quiet_dots: int, canvas: tuple[int, int] | None = None
) -> tuple[Image.Image, bool]:
    """Dunkles Band: Code invertieren (Module ungedruckt) und Ruhezone ringsum schwarz drucken.

    canvas=None -> Ergebnisgröße (w + 2q, h + 2q). Mit canvas=(cw, ch): Ergebnis genau cw×ch,
    Code mittig, Ruhezone so weit sie passt; zweiter Rückgabewert False, wenn die volle
    Ruhezone nicht passte."""
    inverted = ImageChops.invert(image.convert("L")).point(lambda p: 255 if p >= 128 else 0, mode="1")
    w, h = image.size
    if canvas is None:
        out = Image.new("1", (w + 2 * quiet_dots, h + 2 * quiet_dots), 0)
        out.paste(inverted, (quiet_dots, quiet_dots))
        return out, True
    cw, ch = canvas
    out = Image.new("1", (cw, ch), 0)
    x = (cw - w) // 2
    y = (ch - h) // 2
    out.paste(inverted, (x, y))
    fits = x >= quiet_dots and y >= quiet_dots and (cw - w - x) >= quiet_dots and (ch - h - y) >= quiet_dots
    return out, fits
