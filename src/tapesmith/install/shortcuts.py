"""Startmenü-Verknüpfungen (.lnk) ohne Adminrecht.

`WScriptShortcuts` nutzt `win32com.client` (pywin32), spät importiert wie bei `WinRegBackend`,
und schützt sich mit demselben Muster gegen Schreibzugriffe unter `pytest` (Sicherheitsnetz
"Echte Nutzerdaten sind tabu")."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol
from tapesmith.i18n import _t


class ShortcutBackend(Protocol):
    def create(self, path: Path, target: Path, *, arguments: str = "", icon: Path | None = None,
              workdir: Path | None = None, description: str = "") -> None: ...

    def delete(self, path: Path) -> None: ...

    def exists(self, path: Path) -> bool: ...


class FakeShortcuts:
    """Dict-basiertes Verknüpfungs-Backend für Tests."""

    def __init__(self) -> None:
        self.items: dict[Path, dict] = {}

    def create(self, path: Path, target: Path, *, arguments: str = "", icon: Path | None = None,
              workdir: Path | None = None, description: str = "") -> None:
        self.items[Path(path)] = {
            "target": Path(target),
            "arguments": arguments,
            "icon": Path(icon) if icon is not None else None,
            "workdir": Path(workdir) if workdir is not None else None,
            "description": description,
        }

    def delete(self, path: Path) -> None:
        self.items.pop(Path(path), None)

    def exists(self, path: Path) -> bool:
        return Path(path) in self.items


class WScriptShortcuts:
    """Echte .lnk-Dateien über `WScript.Shell` (pywin32). Schreibmethoden verweigern sich
    während `pytest`, `exists` bleibt erlaubt."""

    def _guard(self) -> None:
        if "PYTEST_CURRENT_TEST" in os.environ:
            raise RuntimeError(_t("Verknüpfungs-Schreibzugriff in Tests verboten"))

    def create(self, path: Path, target: Path, *, arguments: str = "", icon: Path | None = None,
              workdir: Path | None = None, description: str = "") -> None:
        self._guard()
        import win32com.client

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        shell = win32com.client.Dispatch("WScript.Shell")
        shortcut = shell.CreateShortcut(str(path))
        shortcut.TargetPath = str(target)
        if arguments:
            shortcut.Arguments = arguments
        shortcut.IconLocation = str(icon) if icon is not None else str(target)
        shortcut.WorkingDirectory = str(workdir) if workdir is not None else str(Path(target).parent)
        if description:
            shortcut.Description = description
        shortcut.Save()

    def delete(self, path: Path) -> None:
        self._guard()
        Path(path).unlink(missing_ok=True)

    def exists(self, path: Path) -> bool:
        return Path(path).exists()


def start_menu_dir() -> Path:
    """`%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\Tapesmith`. Unter pytest nur mit
    `TAPESMITH_START_MENU_DIR` (Sicherheitsnetz gegen das echte Startmenü)."""
    override = os.environ.get("TAPESMITH_START_MENU_DIR")
    if override:
        return Path(override)
    if "PYTEST_CURRENT_TEST" in os.environ:
        raise RuntimeError(
            _t("TAPESMITH_START_MENU_DIR fehlt: unter pytest ist das echte Startmenü gesperrt. Tests brauchen TAPESMITH_START_MENU_DIR=<eigener Temp-Ordner>."))
    return Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Tapesmith"
