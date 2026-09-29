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

APP_EXE = "Tapesmith.exe"
STATE_SCHEMA = 1

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


def _suffix_part_key(part: str) -> tuple[int, Any]:
    return (0, int(part)) if part.isdigit() else (1, part)


def parse_version(text: str) -> tuple:
    """Vergleichbares Tupel: `parse_version("0.10.1") > parse_version("0.9.9")`. Ein Suffix wie
    `-beta.1` sortiert vor der gleichen Endversion ohne Suffix."""
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

    def to_dict(self) -> dict:
        return {
            "schema": STATE_SCHEMA,
            "current": self.current,
            "previous": self.previous,
            "versions": list(self.versions),
            "failed": list(self.failed),
            "installed_at": self.installed_at,
            "channel": self.channel,
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
    return current_link(root) / APP_EXE


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
