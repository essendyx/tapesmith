"""Code128 mit Klartext. Eigener Encoder (render.code128, bitgleich zu zxing-cpp),
Selbsttest per Rücklesen, sofern der Decoder zxing-cpp geladen werden kann."""

from PIL import Image

from tapesmith.render.code128 import encode_modules
from tapesmith.render.codes import CodeResult, self_test_code
from tapesmith.render.zxing import NOT_READ_WARNING
from tapesmith.render.text import fit_text, render_text_block
from tapesmith.i18n import _t

MIN_MODULE_DOTS = 2
QUIET_MODULES = 10
TEXT_GAP_DOTS = 2
MIN_BAR_DOTS = 16
TEXT_MIN_SIZE = 10
TEXT_MAX_SIZE = 24


def code128_modules(data: str) -> str:
    """"1"/"0"-Folge (1 = Balken) ohne Ruhezone, gleich der bisherigen zxing-cpp-Ausgabe."""
    return encode_modules(data)


def code128_width(data: str, module: int) -> int:
    return len(code128_modules(data)) * module


def render_code128(
    data: str, module: int, height: int, *, show_text: bool = True,
    text_size: int | None = None, font: str = "mono", max_width: int | None = None,
) -> CodeResult:
    if module < MIN_MODULE_DOTS:
        raise ValueError(_t("Barcode-Modul muss mindestens 2 Punkte sein"))
    modules = code128_modules(data)
    width = len(modules) * module
    if max_width is not None and width > max_width:
        mm = width / 8
        raise ValueError(_t("Barcode braucht {width} Punkte ({mm:.0f} mm), verfügbar {max_width}", width=width, mm=mm, max_width=max_width))

    warnings: list[str] = []
    text_block = None
    if show_text:
        if text_size is None:
            try:
                block = fit_text(
                    [data], font, max_height=max(TEXT_MIN_SIZE, height // 4),
                    max_width=width, align="center",
                )
            except ValueError as exc:
                raise ValueError(
                    _t("Klartext passt nicht unter den Barcode: show_text aus oder Modul größer")
                ) from exc
            if block.font_size > TEXT_MAX_SIZE:
                block = render_text_block([data], font, TEXT_MAX_SIZE, "center")
            elif block.font_size < TEXT_MIN_SIZE:
                warnings.append(
                    _t("Klartext unter dem Barcode sehr klein (Schrift {font_size} < {text_min_size}): show_text aus oder Box höher", font_size=block.font_size, text_min_size=TEXT_MIN_SIZE)
                )
            text_block = block
        else:
            block = render_text_block([data], font, text_size, "center")
            if block.image.width > width:
                raise ValueError(_t("Klartext breiter als der Barcode (Schrift {text_size})", text_size=text_size))
            text_block = block

    text_height = text_block.image.height + TEXT_GAP_DOTS if text_block is not None else 0
    bar_height = height - text_height
    if bar_height < MIN_BAR_DOTS:
        raise ValueError(_t("Barcode zu niedrig: Balken nur {bar_height} Punkte", bar_height=bar_height))

    bars = Image.new("1", (width, bar_height), 255)
    for x, bit in enumerate(modules):
        if bit == "1":
            bars.paste(0, (x * module, 0, (x + 1) * module, bar_height))

    image = Image.new("1", (width, height), 255)
    image.paste(bars, (0, 0))
    if text_block is not None:
        tx = (width - text_block.image.width) // 2
        image.paste(text_block.image, (tx, bar_height + TEXT_GAP_DOTS))

    quiet = QUIET_MODULES * module
    verified = self_test_code(bars, data, "Code128", quiet)
    if verified is False:
        raise ValueError(_t("Barcode nicht lesbar (Selbsttest)"))
    if verified is None:
        warnings.append(_t(NOT_READ_WARNING))

    if module == MIN_MODULE_DOTS:
        warnings.append(_t("Barcode-Modul 2 Punkte: vor Serieneinsatz einmal mit dem Scanner prüfen"))

    return CodeResult(image, "code128", module, quiet, bool(verified), tuple(warnings))
