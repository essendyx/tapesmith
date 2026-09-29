"""Text in die Windows-Zwischenablage, ohne Qt und ohne Zusatzpaket.

Der ctypes-Zugriff wird erst beim Aufruf aufgebaut, das Modul lädt also auch auf anderen Systemen.
Tests übergeben immer ein eigenes `backend`.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from tapesmith.i18n import _t

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
OPEN_ATTEMPTS = 5
OPEN_WAIT_S = 0.05


def _windows_copy(text: str) -> None:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.CloseClipboard.restype = wintypes.BOOL
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = wintypes.LPVOID
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]

    data = text.encode("utf-16-le") + b"\x00\x00"
    for attempt in range(OPEN_ATTEMPTS):
        if user32.OpenClipboard(None):
            break
        if attempt == OPEN_ATTEMPTS - 1:
            raise RuntimeError(_t("Zwischenablage ist belegt, bitte gleich noch einmal versuchen"))
        time.sleep(OPEN_WAIT_S)
    try:
        if not user32.EmptyClipboard():
            raise RuntimeError(_t("Zwischenablage ließ sich nicht leeren"))
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not handle:
            raise RuntimeError(_t("Kein Speicher für die Zwischenablage"))
        pointer = kernel32.GlobalLock(handle)
        if not pointer:
            kernel32.GlobalFree(handle)
            raise RuntimeError(_t("Speicher der Zwischenablage nicht sperrbar"))
        ctypes.memmove(pointer, data, len(data))
        kernel32.GlobalUnlock(handle)
        if not user32.SetClipboardData(CF_UNICODETEXT, handle):
            kernel32.GlobalFree(handle)
            raise RuntimeError(_t("Text konnte nicht in die Zwischenablage gelegt werden"))
    finally:
        user32.CloseClipboard()


def copy_text(text: str, *, backend: Callable[[str], None] | None = None) -> None:
    """Legt `text` in die Zwischenablage; Fehler als RuntimeError mit deutscher Meldung."""
    if backend is None:
        if sys.platform != "win32":
            raise RuntimeError(_t("Zwischenablage nur unter Windows"))
        backend = _windows_copy
    try:
        backend(text)
    except RuntimeError:
        raise
    except Exception as exc:  # noqa: BLE001 (Backend-Fehler einheitlich melden)
        raise RuntimeError(_t("Zwischenablage nicht beschreibbar: {exc}", exc=exc)) from exc
