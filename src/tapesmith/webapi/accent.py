"""Windows-Akzentfarbe für die Oberfläche (nur lesend aus der Registry)."""

from __future__ import annotations

from collections.abc import Callable


def _registry_accent() -> int | None:
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\DWM") as key:
        value, _kind = winreg.QueryValueEx(key, "AccentColor")
    return int(value)


def read_accent(reader: Callable[[], int | None] | None = None) -> str | None:
    """`AccentColor` (DWORD 0xAABBGGRR) als "#rrggbb"; Fehler oder kein Wert ergibt None."""
    try:
        value = (reader or _registry_accent)()
        if value is None:
            return None
        value = int(value)
        red, green, blue = value & 0xFF, (value >> 8) & 0xFF, (value >> 16) & 0xFF
        return f"#{red:02x}{green:02x}{blue:02x}"
    except Exception:  # noqa: BLE001 (Akzentfarbe ist nur Schmuck)
        return None
