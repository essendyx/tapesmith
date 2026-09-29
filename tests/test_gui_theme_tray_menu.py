"""Tests für den Dunkelmodus des Tray-Kontextmenüs: `system_prefers_dark`,
`effective_dark`, dunkler Farbsatz und Kontrast."""

from PySide6.QtGui import QPalette

from tapesmith.gui.theme import (
    COLORS,
    COLORS_DARK,
    apply_theme,
    build_palette,
    colors,
    effective_dark,
    system_prefers_dark,
)


def _luminance(hex_color: str) -> float:
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i + 2], 16) / 255 for i in (0, 2, 4))

    def lin(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = lin(r), lin(g), lin(b)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(hex_a: str, hex_b: str) -> float:
    la, lb = _luminance(hex_a), _luminance(hex_b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def test_system_prefers_dark_liest_reader():
    assert system_prefers_dark(reader=lambda: 0) is True
    assert system_prefers_dark(reader=lambda: 1) is False


def test_system_prefers_dark_fehler_ist_hell():
    def boom():
        raise OSError("keine Registry")

    assert system_prefers_dark(reader=boom) is False


def test_effective_dark_aus_app_theme():
    assert effective_dark({"app": {"theme": "dunkel"}}) is True
    assert effective_dark({"app": {"theme": "hell"}}) is False
    assert effective_dark({"app": {"theme": "system"}}, reader=lambda: 0) is True
    assert effective_dark({"app": {"theme": "system"}}, reader=lambda: 1) is False
    assert effective_dark(None, reader=lambda: 1) is False


def test_farbsaetze_unterscheiden_sich():
    assert colors(True) is COLORS_DARK
    assert colors(False) is COLORS
    assert COLORS_DARK["window"] != COLORS["window"]


def test_build_palette_dark_setzt_dunkles_fenster(qapp):
    palette = build_palette(dark=True)
    assert palette.color(QPalette.ColorRole.Window).name().lower() == COLORS_DARK["window"].lower()
    palette_light = build_palette(dark=False)
    assert palette_light.color(QPalette.ColorRole.Window).name().lower() == COLORS["window"].lower()


def test_apply_theme_dark_true_setzt_dunkle_palette(qapp):
    apply_theme(qapp, dark=True)
    assert qapp.palette().color(QPalette.ColorRole.Window).name().lower() == COLORS_DARK["window"].lower()
    apply_theme(qapp, dark=False)
    assert qapp.palette().color(QPalette.ColorRole.Window).name().lower() == COLORS["window"].lower()


def test_kontrast_mindestens_4_5_in_beiden_saetzen():
    for palette in (COLORS, COLORS_DARK):
        assert _contrast(palette["text"], palette["surface"]) >= 4.5
        assert _contrast(palette["accent_text"], palette["accent"]) >= 4.5
