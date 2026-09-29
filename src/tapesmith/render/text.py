"""Textsatz in 1 Bit: Auto-Fit auf Höhe und optionale Maximallänge, ohne Kantenglättung."""

from collections.abc import Sequence
from dataclasses import dataclass

from PIL import Image, ImageChops, ImageDraw

from tapesmith.render.fonts import load_font
from tapesmith.i18n import _t

MIN_SIZE = 6
MAX_SIZE = 400
ALIGNS = ("left", "center", "right")


@dataclass(frozen=True)
class TextBlock:
    image: Image.Image
    font_size: int


def _render_line_ink(line: str, font) -> tuple[Image.Image, int] | None:
    """Rendert eine Zeile auf einer grosszuegig gepolsterten Leinwand und schneidet sie auf die
    tatsaechlich gerenderte Tinte zu (statt die Box nur aus den Font-Metriken zu berechnen), damit
    bei kleinen Groessen weder Pixel abgeschnitten werden noch ein leerer Rand entsteht.

    Auf der Messleinwand ist Tinte 255 (Hintergrund 0), weil Image.getbbox() die Box der
    Nicht-Null-Pixel liefert. Gibt (Tinten-Ausschnitt, Abstand oberer Rand->Grundlinie) zurueck,
    oder None, wenn die Zeile keine Tinte erzeugt."""
    ascent, descent = font.getmetrics()
    pad = max(ascent + descent, 8)
    est_x0, _est_y0, est_x1, _est_y1 = font.getbbox(line, anchor="ls")
    left_margin = pad + max(-est_x0, 0)
    width = max(est_x1 - est_x0, 0) + left_margin + pad
    height = ascent + descent + 2 * pad
    canvas = Image.new("1", (width, height), 0)
    draw = ImageDraw.Draw(canvas)
    draw.fontmode = "1"
    origin = (left_margin, pad + ascent)
    draw.text(origin, line, font=font, fill=255, anchor="ls")
    box = canvas.getbbox()
    if box is None:
        return None
    ink = canvas.crop(box)
    return ink, box[1] - origin[1]


def _layout(lines: Sequence[str], font_name: str, size: int):
    """Tinten-Boxen aller Zeilen (aus dem echten Render gemessen) relativ zur ersten Grundlinie;
    Zeilenabstand = ascent + descent."""
    font = load_font(font_name, size)
    ascent, descent = font.getmetrics()
    pitch = ascent + descent
    boxes: list[tuple[Image.Image, int]] = []
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        measured = _render_line_ink(line, font)
        if measured is None:
            continue
        ink, top_offset = measured
        boxes.append((ink, top_offset + i * pitch))
    if not boxes:
        raise ValueError(_t("kein Text zum Setzen"))
    min_y = min(top for _ink, top in boxes)
    max_y = max(top + ink.height for ink, top in boxes)
    width = max(ink.width for ink, _top in boxes)
    return boxes, min_y, max_y, width


def render_text_block(lines: Sequence[str], font: str, size: int, align: str = "left") -> TextBlock:
    if align not in ALIGNS:
        raise ValueError(_t("Unbekannte Ausrichtung '{align}' (erlaubt: {items})", align=align, items=', '.join(ALIGNS)))
    boxes, min_y, max_y, width = _layout(lines, font, size)
    image = Image.new("1", (width, max_y - min_y), 255)
    for ink, top in boxes:
        line_width = ink.width
        if align == "left":
            x = 0
        elif align == "center":
            x = (width - line_width) // 2
        else:
            x = width - line_width
        black_ink = ImageChops.invert(ink.convert("L")).convert("1")
        image.paste(black_ink, (x, top - min_y))
    return TextBlock(image, size)


def ink_extent(lines: Sequence[str], font: str, size: int) -> tuple[int, int, int]:
    """Tinten-Ausdehnung eines Textblocks bei `size`: (oben, unten, Breite), oben/unten relativ zur
    ersten Grundlinie (oben negativ). Grundlage für gemeinsame Grundlinien mehrerer Blöcke."""
    _, min_y, max_y, width = _layout(lines, font, size)
    return min_y, max_y, width


def fit_size(lines: Sequence[str], font: str, max_height: int, max_width: int | None = None) -> int | None:
    """Größte Schriftgröße, bei der der Block in max_height × max_width passt, oder None, wenn
    selbst MIN_SIZE zu groß ist."""
    def fits(size: int) -> bool:
        _, min_y, max_y, width = _layout(lines, font, size)
        return max_y - min_y <= max_height and (max_width is None or width <= max_width)

    if not fits(MIN_SIZE):
        return None
    lo, hi = MIN_SIZE, MAX_SIZE
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if fits(mid):
            lo = mid
        else:
            hi = mid - 1
    return lo


def fit_text(lines: Sequence[str], font: str, max_height: int, max_width: int | None = None,
             align: str = "left") -> TextBlock:
    size = fit_size(lines, font, max_height, max_width)
    if size is None:
        raise ValueError(_t("Text passt nicht: selbst Schriftgröße {min_size} ist zu groß für {max_height} × {value} Punkte", min_size=MIN_SIZE, max_height=max_height, value=max_width if max_width is not None else '∞'))
    return render_text_block(lines, font, size, align)
