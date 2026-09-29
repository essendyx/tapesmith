"""Tests für die HiDPI-Symbole der Tray-App: `draw_icon_image` (reines Pillow) und
`make_status_icon` (Qt). Kein echtes Fenster, alles offscreen."""

from tapesmith.gui.icons import ICON_SIZES, ROLE_COLORS, draw_icon_image, make_status_icon
from tapesmith.gui.tray import make_icon


def _badge_center(size: int) -> tuple[int, int]:
    diameter = max(2, round(size * 0.4))
    c = size - diameter // 2 - 1
    return c, c


def test_jede_groesse_liefert_bild_dieser_groesse():
    for size in ICON_SIZES:
        image = draw_icon_image(size, "success", dark_taskbar=False)
        assert image.size == (size, size)
        assert image.mode == "RGBA"


def test_statuspunkt_farbe_je_rolle():
    cx, cy = _badge_center(32)
    error_img = draw_icon_image(32, "error", dark_taskbar=False)
    assert error_img.getpixel((cx, cy)) == ROLE_COLORS["error"]

    success_img = draw_icon_image(32, "success", dark_taskbar=False)
    assert success_img.getpixel((cx, cy)) == ROLE_COLORS["success"]


def test_ohne_rolle_grundfarbe_am_punktplatz():
    cx, cy = _badge_center(32)
    image = draw_icon_image(32, None, dark_taskbar=False)
    from tapesmith.gui.icons import BACKGROUND

    assert image.getpixel((cx, cy)) == BACKGROUND


def test_16px_keine_halbtransparenten_pixel_am_punktrand():
    """Pillow zeichnet ohne Kantenglättung: jedes Pixel ist voll durchsichtig oder voll
    deckend, auch am Rand des Statuspunkts im kleinsten Symbol."""
    image = draw_icon_image(16, "error", dark_taskbar=False)
    alphas = {image.getpixel((x, y))[3] for x in range(16) for y in range(16)}
    assert alphas <= {0, 255}


def test_ring_farbe_folgt_taskleiste():
    size = 48
    diameter = max(2, round(size * 0.4))
    ring_extra = max(2, min(4, round(size * 0.08)))
    ring_radius = (diameter + ring_extra) // 2
    cx, cy = _badge_center(size)
    # Punkt direkt am äußeren Rand des Rings (innerhalb des Rings, außerhalb des Punkts).
    sample = (cx, cy - ring_radius + 1)

    light = draw_icon_image(size, "error", dark_taskbar=False)
    dark = draw_icon_image(size, "error", dark_taskbar=True)
    assert light.getpixel(sample) != dark.getpixel(sample)


def test_make_status_icon_liefert_alle_qt_groessen(qapp):
    icon = make_status_icon("success", dark_taskbar=False)
    sizes = {(s.width(), s.height()) for s in icon.availableSizes()}
    for size in ICON_SIZES[:-1]:
        assert (size, size) in sizes
    assert (256, 256) not in sizes


def test_tray_make_icon_funktioniert_weiter(qapp):
    icon = make_icon("error")
    assert not icon.isNull()
    sizes = {(s.width(), s.height()) for s in icon.availableSizes()}
    assert (32, 32) in sizes
