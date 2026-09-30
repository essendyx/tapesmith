"""Apps-&-Features-Eintrag unter HKCU: kein Adminrecht nötig."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol

UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\Tapesmith"


class UninstallBackend(Protocol):
    def set_str(self, name: str, value: str) -> None: ...

    def set_dword(self, name: str, value: int) -> None: ...

    def get(self, name: str) -> str | int | None: ...

    def delete_tree(self) -> None: ...


class FakeUninstallRegistry:
    """Dict-basiertes Backend für Tests."""

    def __init__(self) -> None:
        self.values: dict[str, str | int] = {}

    def set_str(self, name: str, value: str) -> None:
        self.values[name] = str(value)

    def set_dword(self, name: str, value: int) -> None:
        self.values[name] = int(value)

    def get(self, name: str) -> str | int | None:
        return self.values.get(name)

    def delete_tree(self) -> None:
        self.values.clear()


class UninstallRegistry:
    """Echtes `HKCU\\...\\Uninstall\\Tapesmith` über `winreg`. Schreibmethoden verweigern sich
    während `pytest` (gleiches Muster wie `integration.WinRegBackend`); `get` bleibt erlaubt."""

    def __init__(self, key: str = UNINSTALL_KEY) -> None:
        self.key = key

    def _guard(self) -> None:
        if "PYTEST_CURRENT_TEST" in os.environ or os.environ.get("TAPESMITH_NO_REGISTRY") == "1":
            raise RuntimeError("Registry-Schreibzugriff in Tests verboten")

    def set_str(self, name: str, value: str) -> None:
        import winreg

        self._guard()
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, self.key, 0, winreg.KEY_WRITE) as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, str(value))

    def set_dword(self, name: str, value: int) -> None:
        import winreg

        self._guard()
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, self.key, 0, winreg.KEY_WRITE) as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, int(value))

    def get(self, name: str) -> str | int | None:
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.key) as key:
                value, _ = winreg.QueryValueEx(key, name)
                return value
        except OSError:
            return None

    def delete_tree(self) -> None:
        import winreg

        self._guard()
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.key, 0, winreg.KEY_ALL_ACCESS):
                pass
        except OSError:
            return
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, self.key)
        except OSError:
            pass


def write_uninstall_entry(reg: UninstallBackend, *, root: Path, version: str, size_kb: int) -> None:
    """Eintrag unter Apps und Features. Deinstalliert wird mit dem Python der aktiven Version:
    `"<Wurzel>\\current\\Scripts\\pythonw.exe" -m tapesmith uninstall` (keine eigene EXE)."""
    root_text = str(root)
    pythonw = str(Path(root_text) / "current" / "Scripts" / "pythonw.exe")
    icon = str(Path(root_text) / "current" / "Lib" / "site-packages" / "tapesmith" / "icons" / "app.ico")
    command = f'"{pythonw}" -m tapesmith uninstall'
    reg.set_str("DisplayName", "Tapesmith")
    reg.set_str("DisplayVersion", version)
    reg.set_str("Publisher", "Tapesmith contributors")
    reg.set_str("InstallLocation", root_text)
    reg.set_str("DisplayIcon", icon)
    reg.set_str("UninstallString", command)
    reg.set_str("QuietUninstallString", f"{command} --quiet")
    reg.set_str("URLInfoAbout", "https://github.com/essendyx/tapesmith")
    reg.set_dword("NoModify", 1)
    reg.set_dword("NoRepair", 1)
    reg.set_dword("EstimatedSize", int(size_kb))


def remove_uninstall_entry(reg: UninstallBackend) -> None:
    reg.delete_tree()
