"""Zustand des Updaters: `UpdateStatus` und `<App-Verzeichnis>/update/state.json`.

Die Datei wird bei jeder Änderung atomar geschrieben; Dienst, `--update-apply` und Tray-App
(liest nur `installed` und `available.version`) teilen sie."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from tapesmith import fileutil, paths

STATES = ("idle", "checking", "downloading", "ready", "installing", "failed")


@dataclass
class UpdateStatus:
    installed: bool = False
    current: str = ""
    previous: str | None = None
    root: str | None = None
    enabled: bool = False
    source: str = ""
    channel: str = "stable"
    auto_install: bool = False
    last_check: str | None = None
    available: dict | None = None
    state: str = "idle"
    error: dict | None = None
    can_rollback: bool = False
    idle_ok: bool = False
    # Die Oberfläche fragt einmal nach der automatischen Prüfung (installierte App, noch nie gefragt, aus).
    consent_needed: bool = False

    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict) -> "UpdateStatus":
        names = {f.name for f in fields(cls)}
        status = cls(**{k: v for k, v in data.items() if k in names})
        if status.state not in STATES:
            status.state = "idle"
        return status


def state_path() -> Path:
    return paths.app_dir() / "update" / "state.json"


def load_status() -> UpdateStatus | None:
    """Gespeicherter Zustand oder None (fehlt oder unlesbar)."""
    try:
        data = json.loads(state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        return UpdateStatus.from_json(data)
    except TypeError:
        return None


def save_status(status: UpdateStatus) -> None:
    fileutil.atomic_write_text(state_path(), json.dumps(status.to_json(), ensure_ascii=False, indent=2))
