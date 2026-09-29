"""Kein Fenster, nirgendwo: tapesmith öffnet nie ein eigenes Fenster,
einen Dialog, ein Popup oder eine MessageBox. Nativ bleiben nur Tray-Symbol und Kontextmenü;
alles andere öffnet einen Browser-Tab, Hinweise laufen als Tray-Benachrichtigung oder ins Log.

Statischer Test über den Quelltext (ohne Kommentare und Texte): kein Modul unter `src/tapesmith`
und kein EXE-Einstieg nutzt Fensterklassen von Qt, `MessageBoxW` & Co. oder zeigt ein Widget an.
"""

from __future__ import annotations

import io
import tokenize
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCES = sorted((ROOT / "src" / "tapesmith").rglob("*.py")) + [ROOT / "tools" / "tapesmith_gui_entry.py"]

# Namen, die ein Fenster bedeuten (Qt-Fensterklassen, Win32-Meldungsfenster, Web-Fenster).
FORBIDDEN_NAMES = {
    "QDialog", "QMessageBox", "QInputDialog", "QFileDialog", "QColorDialog", "QFontDialog",
    "QProgressDialog", "QErrorMessage", "QWizard", "QMainWindow", "QWidget", "QSplashScreen",
    "QDockWidget", "QWebEngineView", "QQuickView", "QQmlApplicationEngine",
    "MessageBoxW", "MessageBoxA", "MessageBoxExW", "MessageBoxIndirectW", "MessageBeep",
    "TaskDialog", "TaskDialogIndirect", "CreateWindowExW", "CreateWindowExA", "DialogBoxParamW",
    "webview", "tkinter", "Tk", "messagebox", "ctypes_messagebox",
}
# Methoden, die ein Fenster anzeigen (Qt-Widgets, auch `Image.show()` von Pillow). Erlaubt ist nur
# das Tray-Symbol selbst (`tray_icon.show()`) und die Qt-Nachrichtenschleife (`app.exec()`).
SHOW_METHODS = {"show", "showNormal", "showMaximized", "showFullScreen", "showMinimized", "exec", "exec_",
                "popup"}
ALLOWED_CALLS = {("tray_icon", "show"), ("app", "exec")}


def _code_tokens(path: Path) -> list[tokenize.TokenInfo]:
    text = path.read_text(encoding="utf-8")
    tokens = tokenize.generate_tokens(io.StringIO(text).readline)
    return [t for t in tokens if t.type not in (tokenize.COMMENT, tokenize.STRING, tokenize.NL,
                                                tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT)]


def _findings(path: Path) -> list[str]:
    rel = path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else path.name
    tokens = _code_tokens(path)
    found = []
    for index, tok in enumerate(tokens):
        if tok.type != tokenize.NAME:
            continue
        if tok.string in FORBIDDEN_NAMES:
            found.append(f"{rel}:{tok.start[0]}: {tok.string} (Fenster oder Meldungsfenster)")
            continue
        if tok.string not in SHOW_METHODS or index < 2:
            continue
        dot, receiver = tokens[index - 1], tokens[index - 2]
        following = tokens[index + 1] if index + 1 < len(tokens) else None
        if dot.string != "." or following is None or following.string != "(":
            continue
        if (receiver.string, tok.string) in ALLOWED_CALLS:
            continue
        found.append(f"{rel}:{tok.start[0]}: {receiver.string}.{tok.string}() zeigt ein Fenster an")
    return found


def test_quellen_gefunden():
    assert len(SOURCES) > 50
    assert (ROOT / "src" / "tapesmith" / "gui" / "tray.py") in SOURCES


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_kein_fenster_im_quelltext(path):
    findings = _findings(path)
    assert not findings, (
        "tapesmith darf kein eigenes Fenster, keinen Dialog und keine MessageBox öffnen "
        "(nur Tray-Symbol plus Kontextmenü; Oberfläche immer als Browser-Tab über "
        "webui.browser.open_app, Hinweise als Tray-Benachrichtigung oder ins Log):\n"
        + "\n".join(findings))


def test_pruefung_erkennt_verstoesse(tmp_path):
    """Gegenprobe: der Scanner findet Fensterklassen, MessageBoxW und angezeigte Widgets."""
    bad = tmp_path / "fenster_probe.py"
    bad.write_text(
        "from PySide6.QtWidgets import QDialog\n"
        "import ctypes\n"
        "ctypes.windll.user32.MessageBoxW(0, 'x', 'y', 0)\n"
        "popup.show()\n"
        "dialog.exec()\n"
        "# QMessageBox im Kommentar ist erlaubt\n"
        "text = 'QWidget im Text ist erlaubt'\n"
        "self.tray_icon.show()\n"
        "app.exec()\n", encoding="utf-8")
    findings = _findings(bad)
    joined = "\n".join(findings)
    assert "QDialog" in joined
    assert "MessageBoxW" in joined
    assert "popup.show()" in joined
    assert "dialog.exec()" in joined
    assert len(findings) == 4, joined
