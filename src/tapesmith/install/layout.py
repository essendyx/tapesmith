"""Installationslayout: Wurzel, Zustand (install.json), Versionsvergleich.

<Wurzel> = %LOCALAPPDATA%\\Programs\\Tapesmith (überschreibbar per TAPESMITH_INSTALL_ROOT bzw.
`--root`). Unter pytest ohne Override sperrt `install_root()` den echten Ordner, genau wie
`paths.app_dir()` für %APPDATA%\\Tapesmith (Sicherheitsnetz "Echte Nutzerdaten sind tabu")."""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from tapesmith import fileutil
from tapesmith.i18n import _t

# Eine Version ist eine eigene Python-Umgebung (venv) unter `versions\\<v>`; gestartet wird immer
# über das signierte `pythonw.exe` dieser Umgebung (`pythonw -m tapesmith...`), nie über eine
# eigene EXE. `APP_EXE` kennzeichnet nur noch Versionsordner des früheren portablen Builds
# (PyInstaller), die eine Installation ablöst (`installer.retire_frozen_versions`).
APP_EXE = "Tapesmith.exe"
VENV_MARKER = "pyvenv.cfg"
VERSION_MARKER = "tapesmith-version.json"
STATE_SCHEMA = 2

GUARD_MESSAGE = (
    "TAPESMITH_INSTALL_ROOT fehlt: unter pytest ist die echte Installation %LOCALAPPDATA%\\Programs\\Tapesmith gesperrt. Tests und manuelle Aufrufe brauchen TAPESMITH_INSTALL_ROOT=<eigener Temp-Ordner>."
)


def _under_pytest() -> bool:
    return "PYTEST_CURRENT_TEST" in os.environ or "pytest" in sys.modules


def install_root() -> Path:
    """Installationswurzel. Legt nichts an. Unter pytest ohne Override: `RuntimeError`."""
    base = os.environ.get("TAPESMITH_INSTALL_ROOT")
    if not base:
        if _under_pytest():
            raise RuntimeError(GUARD_MESSAGE)
        base = os.path.join(os.environ.get("LOCALAPPDATA", str(Path.home())), "Programs", "Tapesmith")
    return Path(base)


# ---------- Versionsvergleich ----------

_VERSION_RE = re.compile(r"^(\d+(?:\.\d+)*)(?:-([A-Za-z0-9.]+))?$")
# Vorabversionen nach PEP 440 (so heißen sie auf PyPI): 0.4.0a1, 0.4.0b2, 0.4.0rc1.
_PEP440_PRE_RE = re.compile(r"^(\d+(?:\.\d+)*)(a|b|rc)(\d+)$")
_PRE_ORDER = {"a": 0, "b": 1, "rc": 2}


def _suffix_part_key(part: str) -> tuple[int, Any]:
    return (0, int(part)) if part.isdigit() else (1, part)


def parse_version(text: str) -> tuple:
    """Vergleichbares Tupel: `parse_version("0.10.1") > parse_version("0.9.9")`. Ein Suffix wie
    `-beta.1` sortiert vor der gleichen Endversion ohne Suffix, ebenso PEP-440-Vorabversionen
    (`0.4.0b1` < `0.4.0rc1` < `0.4.0`)."""
    pre = _PEP440_PRE_RE.match(text.strip())
    if pre:
        nums = tuple(int(p) for p in pre.group(1).split("."))
        return (nums, 0, ((0, _PRE_ORDER[pre.group(2)]), (0, int(pre.group(3)))))
    match = _VERSION_RE.match(text.strip())
    if not match:
        raise ValueError(_t("Ungültige Version: {text!r}", text=text))
    nums = tuple(int(p) for p in match.group(1).split("."))
    suffix = match.group(2)
    if suffix:
        return (nums, 0, tuple(_suffix_part_key(p) for p in suffix.split(".")))
    return (nums, 1, ())


# ---------- Zustand (install.json) ----------

@dataclass
class InstallState:
    current: str | None = None
    previous: str | None = None
    versions: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    installed_at: str | None = None
    channel: str = "stable"
    # Basis-Python (python.exe), mit dem die Versionsumgebungen angelegt werden.
    python: str | None = None

    def to_dict(self) -> dict:
        return {
            "schema": STATE_SCHEMA,
            "current": self.current,
            "previous": self.previous,
            "versions": list(self.versions),
            "failed": list(self.failed),
            "installed_at": self.installed_at,
            "channel": self.channel,
            "python": self.python,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "InstallState":
        return cls(
            current=data.get("current"),
            previous=data.get("previous"),
            versions=list(data.get("versions") or []),
            failed=list(data.get("failed") or []),
            installed_at=data.get("installed_at"),
            channel=data.get("channel", "stable"),
            python=data.get("python"),
        )


def state_path(root: Path | None = None) -> Path:
    return (root or install_root()) / "install.json"


def read_state(root: Path | None = None) -> InstallState | None:
    path = state_path(root)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(_t("install.json unlesbar ({path}): {exc}", path=path, exc=exc)) from exc
    return InstallState.from_dict(data)


def write_state(state: InstallState, root: Path | None = None) -> None:
    path = state_path(root)
    fileutil.atomic_write_text(path, json.dumps(state.to_dict(), ensure_ascii=False, indent=2))


# ---------- Pfade ----------

def version_dir(version: str, root: Path | None = None) -> Path:
    return (root or install_root()) / "versions" / version


def current_link(root: Path | None = None) -> Path:
    return (root or install_root()) / "current"


def current_exe(root: Path | None = None) -> Path:
    """Früherer portabler Build: `current\\Tapesmith.exe` (nur noch zum Erkennen und Ablösen)."""
    return current_link(root) / APP_EXE


def venv_python(env_dir: Path, *, gui: bool = False) -> Path:
    """`<env>\\Scripts\\python.exe` bzw. mit `gui` `pythonw.exe` (ohne Konsolenfenster)."""
    return Path(env_dir) / "Scripts" / ("pythonw.exe" if gui else "python.exe")


def current_pythonw(root: Path | None = None) -> Path:
    """`<Wurzel>\\current\\Scripts\\pythonw.exe`: Startbefehl für Startmenü, Autostart, URI."""
    return venv_python(current_link(root), gui=True)


def is_venv_version(path: Path) -> bool:
    """Versionsordner als Python-Umgebung (`pyvenv.cfg` vorhanden)."""
    return (Path(path) / VENV_MARKER).is_file()


def is_frozen_version(path: Path) -> bool:
    """Versionsordner des früheren portablen Builds (`Tapesmith.exe`, keine Python-Umgebung)."""
    path = Path(path)
    return (path / APP_EXE).is_file() and not is_venv_version(path)


def is_complete_version(path: Path) -> bool:
    """Fertig bereitgestellte Python-Version: Umgebung, `pythonw.exe` und Abschlussmarke."""
    path = Path(path)
    return is_venv_version(path) and venv_python(path, gui=True).is_file() and (path / VERSION_MARKER).is_file()


def _normpath(path: Any) -> str:
    text = os.path.normpath(str(path))
    if text.startswith("\\\\?\\"):
        text = text[4:]
    return text.rstrip("\\").upper()


def running_installed(executable: str | None = None, root: Path | None = None) -> bool:
    """True, wenn `executable` (Default `sys.executable`) unter `<Wurzel>\\versions\\` oder
    `<Wurzel>\\current\\` liegt (Groß/Klein egal)."""
    exe = _normpath(executable or sys.executable)
    r = root if root is not None else install_root()
    versions_dir = _normpath(r) + "\\VERSIONS"
    current_dir = _normpath(r) + "\\CURRENT"
    for base in (versions_dir, current_dir):
        if exe == base or exe.startswith(base + "\\"):
            return True
    return False


def now_iso(now: Callable[[], datetime] | None = None) -> str:
    dt = now() if now is not None else datetime.now(timezone.utc)
    return dt.isoformat()
