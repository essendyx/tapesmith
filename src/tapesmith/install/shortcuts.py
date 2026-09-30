"""Startmenü-Verknüpfungen (.lnk) ohne Adminrecht.

`PowerShellShortcuts` nutzt `WScript.Shell` über das Windows-eigene `powershell.exe` (kein
pywin32 nötig) und schützt sich wie `WinRegBackend` gegen Schreibzugriffe unter `pytest`
(Sicherheitsnetz "Echte Nutzerdaten sind tabu")."""

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


_PS_CREATE = (
    "$ErrorActionPreference='Stop';"
    "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:TS_LNK_PATH);"
    "$s.TargetPath=$env:TS_LNK_TARGET;"
    "if($env:TS_LNK_ARGS){$s.Arguments=$env:TS_LNK_ARGS};"
    "$s.IconLocation=$env:TS_LNK_ICON;"
    "$s.WorkingDirectory=$env:TS_LNK_WORKDIR;"
    "if($env:TS_LNK_DESC){$s.Description=$env:TS_LNK_DESC};"
    "$s.Save()"
)


class PowerShellShortcuts:
    """Echte .lnk-Dateien über `WScript.Shell`, aufgerufen im signierten `powershell.exe` (ohne
    Fenster). Braucht kein pywin32 in der Versionsumgebung. Die Werte gehen als
    Umgebungsvariablen hinein, nie als zusammengesetzter Skripttext. Schreibmethoden verweigern
    sich während `pytest`, `exists` bleibt erlaubt."""

    def __init__(self, runner=None) -> None:
        self.runner = runner

    def _guard(self) -> None:
        if "PYTEST_CURRENT_TEST" in os.environ and self.runner is None:
            raise RuntimeError(_t("Verknüpfungs-Schreibzugriff in Tests verboten"))

    def create(self, path: Path, target: Path, *, arguments: str = "", icon: Path | None = None,
              workdir: Path | None = None, description: str = "") -> None:
        import subprocess

        self._guard()
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        env = {**os.environ,
               "TS_LNK_PATH": str(path), "TS_LNK_TARGET": str(target), "TS_LNK_ARGS": arguments,
               "TS_LNK_ICON": str(icon) if icon is not None else str(target),
               "TS_LNK_WORKDIR": str(workdir) if workdir is not None else str(Path(target).parent),
               "TS_LNK_DESC": description}
        run = self.runner or subprocess.run
        result = run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", _PS_CREATE],
                     env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
                     timeout=60, creationflags=0x08000000)
        if result.returncode != 0:
            raise OSError(_t("Verknüpfung {path} nicht angelegt: {detail}", path=path,
                             detail=(result.stderr or result.stdout or "").strip()[-300:]))

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
