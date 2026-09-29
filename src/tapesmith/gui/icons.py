"""HiDPI-Symbole der Tray-App: ein App-Symbol in mehreren Pixelgrößen, mit optionalem
Statusabzeichen unten rechts, statt des unleserlichen „P12“-Texts (bisher `tray.make_icon`).

Dieselbe Zeichnung (`draw_icon_image`, reines Pillow) dient sowohl dem Qt-Symbol
(`make_status_icon`) als auch `app.ico` (`tools/make_app_icon.py`). Pillow zeichnet Formen ohne
Kantenglättung: auch das 16-px-Symbol bekommt dadurch keine halbtransparenten Pixel am Rand des
Statuspunkts.
"""

from __future__ import annotations

import io

from PIL import Image, ImageDraw

ICON_SIZES: tuple[int, ...] = (16, 20, 24, 32, 40, 48, 64, 256)

BACKGROUND = (0x00, 0x78, 0xD4, 255)     # #0078D4
FOREGROUND = (0xFF, 0xFF, 0xFF, 255)
ROLE_COLORS: dict[str, tuple[int, int, int, int]] = {
    "success": (0x10, 0x7C, 0x10, 255),
    "warning": (0xF7, 0x63, 0x0C, 255),
    "error": (0xC4, 0x2B, 0x1C, 255),
    "secondary": (0x8A, 0x88, 0x86, 255),
}
BADGE_RING_DARK = (0x20, 0x20, 0x20, 255)      # #202020
BADGE_RING_LIGHT = (0xF3, 0xF3, 0xF3, 255)     # #F3F3F3

MIN_SIZE_FOR_DETAIL = 20   # ab hier: Anhänger mit Loch statt nur Umriss
MIN_SIZE_FOR_LINES = 32    # ab hier: zusätzlich zwei kurze Textstriche


def _badge_geometry(size: int) -> tuple[int, int, int]:
    """Mittelpunkt (x, y) und Durchmesser des Statuspunkts unten rechts (40 % der Größe)."""
    diameter = max(2, round(size * 0.4))
    cx = size - diameter // 2 - 1
    cy = size - diameter // 2 - 1
    return cx, cy, diameter


def _draw_tag_outline(draw: ImageDraw.ImageDraw, size: int) -> None:
    """Unter 20 px: nur der Anhänger-Umriss (Form wie `_draw_tag`, aber ohne Füllung und ohne
    Textstriche), damit das Symbol auch winzig als Etikett erkennbar bleibt."""
    pad = max(1, round(size * 0.22))
    left, top, right, bottom = pad, pad, size - 1 - pad, size - 1 - pad
    width, height = right - left, bottom - top
    if width <= 2 or height <= 2:
        line_w = max(1, round(size * 0.12))
        draw.rectangle((pad, pad, size - 1 - pad, size - 1 - pad), outline=FOREGROUND, width=line_w)
        return
    tip = left + max(1, round(width * 0.28))
    points = [(left, top + height // 2), (tip, top), (right, top), (right, bottom), (tip, bottom)]
    draw.polygon(points, outline=FOREGROUND)
    hole_d = max(1, round(size * 0.09))
    hole_cx = left + max(1, round((tip - left) * 0.45))
    hole_cy = top + height // 2
    draw.ellipse((hole_cx - hole_d // 2, hole_cy - hole_d // 2, hole_cx + hole_d // 2, hole_cy + hole_d // 2),
                 outline=FOREGROUND)


def _draw_tag(draw: ImageDraw.ImageDraw, size: int) -> None:
    """Weißes Etikett-Symbol (Anhänger mit Loch), Linien auf ganze Pixel gerundet; ab 32 px
    zusätzlich zwei kurze Textstriche."""
    pad = max(1, round(size * 0.22))
    left, top, right, bottom = pad, pad, size - 1 - pad, size - 1 - pad
    width, height = right - left, bottom - top
    if width <= 1 or height <= 1:
        _draw_tag_outline(draw, size)
        return
    tip = left + max(1, round(width * 0.28))
    points = [(left, top + height // 2), (tip, top), (right, top), (right, bottom), (tip, bottom)]
    draw.polygon(points, fill=FOREGROUND)
    hole_d = max(1, round(size * 0.09))
    hole_cx = left + max(1, round((tip - left) * 0.45))
    hole_cy = top + height // 2
    draw.ellipse((hole_cx - hole_d // 2, hole_cy - hole_d // 2, hole_cx + hole_d // 2, hole_cy + hole_d // 2),
                 fill=BACKGROUND)
    if size >= MIN_SIZE_FOR_LINES:
        line_x1 = tip + max(1, round(width * 0.14))
        line_x2 = right - max(1, round(width * 0.14))
        line_w = max(1, round(size * 0.05))
        line_y1 = top + round(height * 0.38)
        line_y2 = top + round(height * 0.62)
        draw.line((line_x1, line_y1, line_x2, line_y1), fill=BACKGROUND, width=line_w)
        draw.line((line_x1, line_y2, line_x2 - max(1, round(width * 0.15)), line_y2), fill=BACKGROUND,
                  width=line_w)


def draw_icon_image(size: int, role: str | None, *, dark_taskbar: bool) -> Image.Image:
    """RGBA-Bild (`size` x `size`): abgerundetes blaues Quadrat (Radius 22 % der Größe) mit
    weißem Etikett-Symbol, bei `role` zusätzlich ein Statuspunkt unten rechts (Durchmesser 40 %
    der Größe) mit 1 bis 2 px Rand in der Taskleistenfarbe."""
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    radius = max(1, round(size * 0.22))
    draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=BACKGROUND)
    if size >= MIN_SIZE_FOR_DETAIL:
        _draw_tag(draw, size)
    else:
        _draw_tag_outline(draw, size)
    if role is not None:
        cx, cy, diameter = _badge_geometry(size)
        ring_extra = max(2, min(4, round(size * 0.08)))
        ring_d = diameter + ring_extra
        ring = BADGE_RING_DARK if dark_taskbar else BADGE_RING_LIGHT
        draw.ellipse((cx - ring_d // 2, cy - ring_d // 2, cx + ring_d // 2, cy + ring_d // 2), fill=ring)
        color = ROLE_COLORS.get(role, ROLE_COLORS["secondary"])
        draw.ellipse((cx - diameter // 2, cy - diameter // 2, cx + diameter // 2, cy + diameter // 2),
                     fill=color)
    return image


def make_status_icon(role: str, *, dark_taskbar: bool | None = None):
    """`QIcon` mit einem `QPixmap` je Größe aus `ICON_SIZES[:-1]` (256 px ist nur für `app.ico`
    gedacht). `dark_taskbar=None` liest `theme.system_prefers_dark()`."""
    from PySide6.QtGui import QIcon, QPixmap

    if dark_taskbar is None:
        from tapesmith.gui.theme import system_prefers_dark

        dark_taskbar = system_prefers_dark()
    icon = QIcon()
    for size in ICON_SIZES[:-1]:
        image = draw_icon_image(size, role, dark_taskbar=dark_taskbar)
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        pixmap = QPixmap()
        pixmap.loadFromData(buf.getvalue(), "PNG")
        icon.addPixmap(pixmap)
    return icon
