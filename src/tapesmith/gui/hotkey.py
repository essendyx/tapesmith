"""Globale Tastenkürzel der Tray-App: Registrierung über `RegisterHotKey`.

Parser, Anzeige und AltGr-Prüfung liegen Qt-frei in `tapesmith.hotkeyspec` (hier weiter
importierbar). Registriert wird ohne eigenes Fenster (`hwnd` = NULL): Windows stellt `WM_HOTKEY`
dann als Thread-Nachricht in die Nachrichtenschlange des Qt-Hauptthreads, `HotkeyManager.native_filter`
fängt sie dort ab. Tests nutzen Fake-Backend und Fake-Probe.
"""

from __future__ import annotations

import ctypes
from collections.abc import Callable
from ctypes import wintypes
from typing import Protocol

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Signal

from tapesmith.hotkeyspec import (  # noqa: F401: Wiederexport für bestehende Aufrufer
    GERMAN_ALTGR,
    MOD_ALT,
    MOD_CONTROL,
    MOD_NOREPEAT,
    MOD_SHIFT,
    MOD_WIN,
    VK_CONTROL,
    VK_L,
    VK_MENU,
    VK_SHIFT,
    FakeLayoutProbe,
    HotkeySpec,
    LayoutProbe,
    WinLayoutProbe,
    altgr_conflict,
    format_hotkey,
    parse_hotkey,
)
from tapesmith.i18n import _t

WM_HOTKEY = 0x0312

_NATIVE_TYPES = (b"windows_generic_MSG", b"windows_dispatcher_MSG")


# ---------- Registrierung ----------

class HotkeyBackend(Protocol):
    def register(self, hwnd: int, hotkey_id: int, modifiers: int, vk: int) -> bool: ...
    def unregister(self, hwnd: int, hotkey_id: int) -> None: ...


class Win32HotkeyBackend:
    """`user32.RegisterHotKey`/`UnregisterHotKey`."""

    def __init__(self) -> None:
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._user32.RegisterHotKey.restype = wintypes.BOOL
        self._user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        self._user32.UnregisterHotKey.restype = wintypes.BOOL
        self._user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]

    def register(self, hwnd: int, hotkey_id: int, modifiers: int, vk: int) -> bool:
        return bool(self._user32.RegisterHotKey(hwnd or None, hotkey_id, modifiers, vk))

    def unregister(self, hwnd: int, hotkey_id: int) -> None:
        self._user32.UnregisterHotKey(hwnd or None, hotkey_id)


class _HotkeyFilter(QAbstractNativeEventFilter):
    def __init__(self, manager: "HotkeyManager") -> None:
        super().__init__()
        self._manager = manager

    def nativeEventFilter(self, eventType, message):  # noqa: N802: Qt-Signatur
        kind = bytes(eventType.data()) if hasattr(eventType, "data") else bytes(eventType)
        # Qt liefert einen shiboken VoidPtr, dessen bool() immer False ist: nur int() taugt.
        address = int(message) if message is not None else 0
        if kind not in _NATIVE_TYPES or not address:
            return False, 0
        msg = wintypes.MSG.from_address(address)
        if msg.message == WM_HOTKEY and self._manager.handle_hotkey_id(int(msg.wParam)):
            return True, 0
        return False, 0


class HotkeyManager(QObject):
    """Registriert benannte Tastenkürzel und meldet sie als `triggered(name)`."""

    triggered = Signal(str)

    def __init__(self, *, backend: HotkeyBackend | None = None, probe: LayoutProbe | None = None,
                 hwnd_provider: Callable[[], int] = lambda: 0, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._backend = backend if backend is not None else Win32HotkeyBackend()
        self.probe = probe if probe is not None else WinLayoutProbe()
        self._hwnd_provider = hwnd_provider
        self._ids: dict[str, int] = {}
        self._specs: dict[str, HotkeySpec] = {}
        self._hwnds: dict[str, int] = {}
        self._next_id = 1
        self._filter: _HotkeyFilter | None = None

    def _id_for(self, name: str) -> int:
        if name not in self._ids:
            self._ids[name] = self._next_id
            self._next_id += 1
        return self._ids[name]

    def _release(self, name: str) -> None:
        if name in self._specs:
            self._backend.unregister(self._hwnds.pop(name, 0), self._ids[name])
            del self._specs[name]

    def register(self, name: str, text: str) -> str | None:
        """Registriert `text` unter `name`; Fehlertext oder None bei Erfolg."""
        try:
            spec = parse_hotkey(text)
        except ValueError as exc:
            return str(exc)
        conflict = altgr_conflict(spec, self.probe)
        if conflict is not None:
            return conflict
        self._release(name)
        hotkey_id = self._id_for(name)
        hwnd = int(self._hwnd_provider() or 0)
        if not self._backend.register(hwnd, hotkey_id, spec.modifiers | MOD_NOREPEAT, spec.vk):
            return _t("{format_hotkey} ist schon von einem anderen Programm belegt", format_hotkey=format_hotkey(spec))
        self._specs[name] = spec
        self._hwnds[name] = hwnd
        return None

    def unregister_all(self) -> None:
        for name in list(self._specs):
            self._release(name)

    def registered(self) -> dict[str, HotkeySpec]:
        return dict(self._specs)

    def handle_hotkey_id(self, hotkey_id: int) -> bool:
        for name, known in self._ids.items():
            if known == hotkey_id and name in self._specs:
                self.triggered.emit(name)
                return True
        return False

    def native_filter(self) -> QAbstractNativeEventFilter:
        if self._filter is None:
            self._filter = _HotkeyFilter(self)
        return self._filter
