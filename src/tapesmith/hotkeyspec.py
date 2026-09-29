"""Tastenkürzel ohne Qt: Parser, Anzeige und AltGr-Prüfung (von Tray und Web-Einstellungen genutzt).

`parse_hotkey` versteht deutsche und englische Namen („Strg+Alt+Umschalt+L“, „Ctrl+Alt+L“).
Auf deutschen Tastaturen ist Strg+Alt dasselbe wie AltGr: ein Kürzel wie Strg+Alt+Q würde
das „@“ schlucken. `altgr_conflict` fragt deshalb das aktuelle Tastaturlayout (`LayoutProbe`)
und lehnt solche Kürzel ab. Die Registrierung (Qt-Nachrichtenschleife) liegt in `gui.hotkey`.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from typing import Protocol
from tapesmith.i18n import _t

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000

VK_SHIFT, VK_CONTROL, VK_MENU = 0x10, 0x11, 0x12
VK_L = 0x4C

_MOD_ALIASES = {
    "strg": MOD_CONTROL, "ctrl": MOD_CONTROL, "control": MOD_CONTROL,
    "alt": MOD_ALT,
    "umschalt": MOD_SHIFT, "shift": MOD_SHIFT,
    "win": MOD_WIN,
}
_MOD_NAMES = ((MOD_CONTROL, "Strg"), (MOD_ALT, "Alt"), (MOD_SHIFT, "Umschalt"), (MOD_WIN, "Win"))

GERMAN_ALTGR = {"Q": "@", "E": "€", "M": "µ", "2": "²", "3": "³", "7": "{", "8": "[", "9": "]", "0": "}"}

@dataclass(frozen=True)
class HotkeySpec:
    modifiers: int          # ohne MOD_NOREPEAT
    vk: int                 # A bis Z = 0x41 bis 0x5A, 0 bis 9 = 0x30 bis 0x39, F1 bis F24 = 0x70 bis 0x87
    key: str                # "L", "7", "F9"


def _parse_key(token: str) -> tuple[int, str]:
    upper = token.upper()
    if len(upper) == 1 and ("A" <= upper <= "Z" or "0" <= upper <= "9"):
        return ord(upper), upper
    if upper.startswith("F") and upper[1:].isdigit() and upper[1:].isascii():
        number = int(upper[1:])
        if 1 <= number <= 24:
            return 0x70 + number - 1, f"F{number}"
    raise ValueError(_t("Taste „{token}“ ist nicht erlaubt, nur A bis Z, 0 bis 9 oder F1 bis F24", token=token))


def parse_hotkey(text: str) -> HotkeySpec:
    """„Strg+Alt+L“ -> `HotkeySpec`. Fehler -> `ValueError` mit deutscher Meldung."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError(_t("Kein Tastenkürzel angegeben"))
    tokens = [part.strip() for part in text.split("+")]
    if any(not token for token in tokens):
        raise ValueError(_t("Tastenkürzel „{text}“ ist unvollständig (z. B. „Strg+Alt+L“)", text=text))
    modifiers = 0
    keys: list[str] = []
    for token in tokens:
        mod = _MOD_ALIASES.get(token.casefold())
        if mod is not None:
            modifiers |= mod
        else:
            keys.append(token)
    if len(keys) != 1:
        raise ValueError(_t("Tastenkürzel „{text}“ braucht genau eine Taste (A bis Z, 0 bis 9, F1 bis F24)", text=text))
    vk, key = _parse_key(keys[0])
    if not modifiers & (MOD_CONTROL | MOD_ALT | MOD_WIN):
        raise ValueError(_t("Tastenkürzel „{text}“ braucht Strg, Alt oder Win", text=text))
    if modifiers & MOD_WIN and vk == VK_L:
        raise ValueError(_t("Win+L sperrt Windows, bitte ein anderes Kürzel wählen"))
    return HotkeySpec(modifiers, vk, key)


def format_hotkey(spec: HotkeySpec) -> str:
    names = [name for mod, name in _MOD_NAMES if spec.modifiers & mod]
    return "+".join([*names, spec.key])


# ---------- Tastaturlayout ----------

class LayoutProbe(Protocol):
    def altgr_char(self, vk: int, shift: bool) -> str | None: ...


class FakeLayoutProbe:
    """Layout-Attrappe für Tests: `table` für Strg+Alt+Taste, `shift_table` mit Umschalt."""

    def __init__(self, table: dict[str, str], shift_table: dict[str, str] | None = None):
        self._table = dict(table)
        self._shift = dict(shift_table or {})

    def altgr_char(self, vk: int, shift: bool) -> str | None:
        key = chr(vk) if 0x30 <= vk <= 0x5A else ""
        return (self._shift if shift else self._table).get(key)


class WinLayoutProbe:
    """Fragt das aktuelle Tastaturlayout über `ToUnicodeEx` (ohne den Tastaturzustand zu ändern)."""

    DONT_CHANGE_STATE = 0x4

    def __init__(self) -> None:
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._user32.GetKeyboardLayout.restype = ctypes.c_void_p
        self._user32.GetKeyboardLayout.argtypes = [wintypes.DWORD]
        self._user32.MapVirtualKeyExW.restype = wintypes.UINT
        self._user32.MapVirtualKeyExW.argtypes = [wintypes.UINT, wintypes.UINT, ctypes.c_void_p]
        self._user32.ToUnicodeEx.restype = ctypes.c_int
        self._user32.ToUnicodeEx.argtypes = [wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_ubyte),
                                             wintypes.LPWSTR, ctypes.c_int, wintypes.UINT, ctypes.c_void_p]

    def altgr_char(self, vk: int, shift: bool) -> str | None:
        user32 = self._user32
        hkl = user32.GetKeyboardLayout(0)
        scan = user32.MapVirtualKeyExW(vk, 0, hkl)
        state = (ctypes.c_ubyte * 256)()
        state[VK_CONTROL] = 0x80
        state[VK_MENU] = 0x80
        if shift:
            state[VK_SHIFT] = 0x80
        buf = ctypes.create_unicode_buffer(8)
        count = user32.ToUnicodeEx(vk, scan, state, buf, len(buf), self.DONT_CHANGE_STATE, hkl)
        if count < 0:
            # Totzeichen: ein zweiter Aufruf setzt den Zustand der Tastatur zurück
            char = buf.value[:1]
            user32.ToUnicodeEx(vk, scan, state, ctypes.create_unicode_buffer(8), 8,
                               self.DONT_CHANGE_STATE, hkl)
            return char or None
        if count == 0:
            return None
        text = buf.value[:count]
        if not text or any(ord(ch) < 0x20 for ch in text):
            return None      # Steuerzeichen (Strg+Taste) sind kein AltGr-Zeichen
        return text


def altgr_conflict(spec: HotkeySpec, probe: LayoutProbe) -> str | None:
    """Fehlertext, wenn Strg+Alt(+Umschalt)+Taste im aktuellen Layout ein Zeichen erzeugt."""
    mods = spec.modifiers
    if not (mods & MOD_CONTROL and mods & MOD_ALT) or mods & MOD_WIN:
        return None
    char = probe.altgr_char(spec.vk, bool(mods & MOD_SHIFT))
    if not char:
        return None
    return (_t("{format_hotkey} erzeugt auf dieser Tastatur „{char}“ (AltGr), bitte eine andere Taste wählen", format_hotkey=format_hotkey(spec), char=char))
