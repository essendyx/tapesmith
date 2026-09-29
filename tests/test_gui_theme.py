"""Tests für das Theme des Tray-Kontextmenüs (Fusion plus eigene Palette).

Seit „kein Fenster“ gibt es nur noch das Kontextmenü als Qt-Oberfläche: Stylesheet, Rollen und
HiDPI-Vorbereitung für Fensterinhalte sind entfernt."""

from PySide6.QtGui import QPalette

from tapesmith.gui import theme
from tapesmith.gui.theme import COLORS, apply_theme


def test_apply_theme_setzt_fusion_und_palette(qapp):
    apply_theme(qapp, dark=False)
    assert qapp.style().name().lower() == "fusion"
    highlight = qapp.palette().color(QPalette.ColorRole.Highlight).name().lower()
    assert highlight == COLORS["accent"].lower()
    assert qapp.styleSheet() == ""


def test_nur_menue_teile_uebrig():
    for name in ("stylesheet", "set_role", "configure_hidpi", "ROLES"):
        assert not hasattr(theme, name), name
