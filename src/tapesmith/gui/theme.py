"""Hell und Dunkel für das Tray-Kontextmenü (Qt „Fusion“ plus eigene Palette).

Die Tray-App hat kein eigenes Fenster: das Kontextmenü ist die einzige Qt-Oberfläche. Ihr
Dunkelmodus folgt `app.theme` (`hell`, `dunkel`, `system`); bei `system` entscheidet
die Windows-Registry (`AppsUseLightTheme`, `system_prefers_dark`, auch für die Symbolfarbe in
`gui.icons`).
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication

COLORS: dict[str, str] = {
    "window": "#F3F3F3", "surface": "#FFFFFF", "border": "#E5E5E5",
    "text": "#1B1B1B", "text_secondary": "#5F5F5F",
    "accent": "#005FB8", "accent_text": "#FFFFFF",
}
COLORS_DARK: dict[str, str] = {
    "window": "#202020", "surface": "#2B2B2B", "border": "#3D3D3D",
    "text": "#FFFFFF", "text_secondary": "#C5C5C5",
    "accent": "#60CDFF", "accent_text": "#000000",
}


def colors(dark: bool = False) -> dict[str, str]:
    """Aktiver Farbsatz (hell oder dunkel)."""
    return COLORS_DARK if dark else COLORS


def system_prefers_dark(reader: Callable[[], int] | None = None) -> bool:
    """True, wenn Windows dunkel eingestellt ist (`AppsUseLightTheme` == 0 in
    `HKCU\\...\\Themes\\Personalize`). `reader` ersetzt den echten Registry-Zugriff in Tests
    (liefert den rohen `AppsUseLightTheme`-Wert). Jeder Fehler ergibt False (hell)."""
    try:
        if reader is not None:
            value = reader()
        else:
            import winreg

            key_path = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                value, _kind = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return int(value) == 0
    except Exception:  # noqa: BLE001 (jede Störung heißt: hell)
        return False


def effective_dark(cfg: dict | None, reader: Callable[[], int] | None = None) -> bool:
    """Wirksamer Dunkelmodus aus `app.theme`: `hell` False, `dunkel` True, `system` Registry
    (`system_prefers_dark`)."""
    from tapesmith import config

    setting = config.setting(cfg if cfg is not None else {}, "app.theme")
    if setting == "hell":
        return False
    if setting == "dunkel":
        return True
    return system_prefers_dark(reader)


def build_palette(dark: bool = False) -> QPalette:
    """Palette für das Kontextmenü (Fläche, Text, Hervorhebung, Trennlinie)."""
    c = colors(dark)
    palette = QPalette()
    window = QColor(c["window"])
    surface = QColor(c["surface"])
    text = QColor(c["text"])
    accent = QColor(c["accent"])
    palette.setColor(QPalette.ColorRole.Window, window)
    palette.setColor(QPalette.ColorRole.WindowText, text)
    palette.setColor(QPalette.ColorRole.Base, surface)
    palette.setColor(QPalette.ColorRole.AlternateBase, window)
    palette.setColor(QPalette.ColorRole.Text, text)
    palette.setColor(QPalette.ColorRole.Button, surface)
    palette.setColor(QPalette.ColorRole.ButtonText, text)
    palette.setColor(QPalette.ColorRole.ToolTipBase, surface)
    palette.setColor(QPalette.ColorRole.ToolTipText, text)
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(c["text_secondary"]))
    palette.setColor(QPalette.ColorRole.Highlight, accent)
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(c["accent_text"]))
    palette.setColor(QPalette.ColorRole.Mid, QColor(c["border"]))
    for group in (QPalette.ColorGroup.Disabled,):
        palette.setColor(group, QPalette.ColorRole.Text, QColor(c["text_secondary"]))
        palette.setColor(group, QPalette.ColorRole.WindowText, QColor(c["text_secondary"]))
        palette.setColor(group, QPalette.ColorRole.ButtonText, QColor(c["text_secondary"]))
    return palette


def apply_theme(app: QApplication, dark: bool | None = None) -> None:
    """Fusion-Stil und Palette (hell oder dunkel) für das Kontextmenü setzen; Schrift nach
    Verfügbarkeit von „Segoe UI Variable“/„Segoe UI“.

    `dark=None` ermittelt den Modus über `effective_dark(config.load_config())`; schlägt das
    Laden der Konfiguration fehl, gilt die Systemeinstellung (`system_prefers_dark()`)."""
    if dark is None:
        try:
            from tapesmith import config

            dark = effective_dark(config.load_config())
        except Exception:  # noqa: BLE001 (kaputte Konfiguration: Systemeinstellung)
            dark = system_prefers_dark()
    app.setStyle("Fusion")
    app.setPalette(build_palette(dark))

    families = QFontDatabase.families()
    if "Segoe UI Variable" in families:
        app.setFont(QFont("Segoe UI Variable", 10))
    elif "Segoe UI" in families:
        app.setFont(QFont("Segoe UI", 10))
