"""Einstellbare Schriftgröße für Vorlagen (Feld `schriftgroesse`).

Werte: "auto" (automatisch; bei Raster-Vorlagen eine einheitliche Größe für alle Felder),
"auto-feld" (nur Raster: jedes Feld einzeln maximal eingepasst, das frühere Verhalten) oder eine
feste Texthöhe in Millimetern. Die Texthöhe ist der Schriftgrad (Geviert) in mm, also dieselbe
Umrechnung wie `checks.min_font_mm`: Schriftgröße in Punkten = mm × Punkte je mm.
"""

from __future__ import annotations

from tapesmith.render.text import MAX_SIZE, MIN_SIZE
from tapesmith.i18n import N_, _t

TEXT_SIZE_FIELD = "schriftgroesse"
TEXT_SIZE_LABEL = N_("Schriftgröße")
AUTO = "auto"
AUTO_FIELD = "auto-feld"
FIXED_MM: tuple[float, ...] = (2, 2.5, 3, 3.5, 4, 4.5, 5, 6, 7, 8, 9)
MIN_MM = 1.0
MAX_MM = 11.0

_AUTO_ALIASES = {"", "auto", "automatisch", "einheitlich", "automatisch (einheitlich)"}
_AUTO_FIELD_ALIASES = {"auto-feld", "auto_feld", "je-feld", "je feld", "feld", "automatisch je feld"}


class TextSizeError(ValueError):
    pass


def format_mm(mm: float) -> str:
    """Kanonische Schreibweise einer festen Größe: "5", "2.5"."""
    return f"{mm:g}"


def choices(per_field: bool) -> tuple[str, ...]:
    head = (AUTO, AUTO_FIELD) if per_field else (AUTO,)
    return head + tuple(format_mm(mm) for mm in FIXED_MM)


def parse(value: str | float | int | None) -> str | float:
    """AUTO, AUTO_FIELD oder eine feste Texthöhe in mm. Komma und Einheit "mm" sind erlaubt."""
    if value is None:
        return AUTO
    if isinstance(value, bool):
        raise TextSizeError(_t("Schriftgröße '{value}' ungültig", value=value))
    if isinstance(value, (int, float)):
        mm = float(value)
    else:
        text = value.strip().lower()
        if text in _AUTO_ALIASES:
            return AUTO
        if text in _AUTO_FIELD_ALIASES:
            return AUTO_FIELD
        number = text.removesuffix("mm").strip().replace(",", ".")
        try:
            mm = float(number)
        except ValueError:
            raise TextSizeError(
                _t("Schriftgröße '{value}' ungültig (erlaubt: auto, auto-feld oder Texthöhe in mm, z. B. 5 oder 3,5)", value=value)) from None
    if not MIN_MM <= mm <= MAX_MM:
        raise TextSizeError(_t("Schriftgröße {format_mm} mm außerhalb von {min_mm:g} bis {max_mm:g} mm", format_mm=format_mm(mm), min_mm=MIN_MM, max_mm=MAX_MM))
    return mm


def canonical(value: str | float | int | None) -> str:
    parsed = parse(value)
    return parsed if isinstance(parsed, str) else format_mm(parsed)


def mm_to_font_size(mm: float, dots_per_mm: int) -> int:
    return max(MIN_SIZE, min(MAX_SIZE, round(mm * dots_per_mm)))


def font_size_to_mm(size: int, dots_per_mm: int) -> float:
    return size / dots_per_mm


def mm_text(mm: float) -> str:
    """Deutsche Anzeige, z. B. "3,5 mm"."""
    return f"{mm:.1f}".replace(".", ",") + " mm"


def shrink_warning(where: str, wanted_mm: float, actual_mm: float) -> str:
    return (_t("Schriftgröße {mm_text} passt nicht in {where}, verkleinert auf {mm_text2}", mm_text=mm_text(wanted_mm), where=where, mm_text2=mm_text(actual_mm)))
