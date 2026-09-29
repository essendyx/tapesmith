"""Druckbarkeits-Warnungen (Minimalform): warnen, nie blockieren."""

from tapesmith.i18n import LANGUAGES, N_, _t, translate
from tapesmith.render.qr import QrResult

MIN_FONT_SIZE = 16
LONG_LABEL_MM = 200.0
SMALL_FONT = N_("Schrift sehr klein ({font_size} Punkte < {min_font_size}), schwer lesbar")


def small_font_warning(font_size: int) -> str:
    return _t(SMALL_FONT, font_size=font_size, min_font_size=MIN_FONT_SIZE)


def is_small_font_warning(text: str) -> bool:
    """True für die Warnung `SMALL_FONT` in jeder Sprache (Text bis zur ersten Klammer)."""
    return any(text.startswith(translate(SMALL_FONT, lang).split("(")[0].rstrip()) for lang in LANGUAGES)


def printability_warnings(font_size: int | None, qr: QrResult | None, length_mm: float) -> list[str]:
    warnings: list[str] = []
    if font_size is not None and font_size < MIN_FONT_SIZE:
        warnings.append(small_font_warning(font_size))
    if qr is not None:
        warnings.extend(qr.warnings)
    if length_mm > LONG_LABEL_MM:
        warnings.append(_t("Label ungewöhnlich lang ({length_mm:.0f} mm)", length_mm=length_mm))
    return warnings
