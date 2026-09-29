"""Sitzungsdatei der Web-Oberfläche (`<App-Verzeichnis>/web/session.json`): Port, Token, PID."""

from __future__ import annotations

import json
import secrets
from datetime import datetime
from pathlib import Path

from tapesmith import fileutil, paths


def session_path() -> Path:
    return paths.app_dir() / "web" / "session.json"


_TOKEN_MIN_LEN = 32


def token_path() -> Path:
    return paths.app_dir() / "web" / "token"


def load_or_create_token() -> str:
    """Sitzungstoken der lokalen Web-Oberfläche. Einmal zufällig erzeugt und danach über Neustarts
    des Dienstes hinweg wiederverwendet, damit offene Browser-Tabs gültig bleiben. Die Datei liegt
    im Benutzerprofil wie die übrigen App-Daten. Fehlt sie oder ist sie ungültig, entsteht eine neue."""
    try:
        token = token_path().read_text(encoding="utf-8").strip()
    except OSError:
        token = ""
    if len(token) >= _TOKEN_MIN_LEN and token.replace("-", "").replace("_", "").isalnum():
        return token
    return reset_token()


def reset_token() -> str:
    """Neues Token erzeugen; alle offenen Tabs müssen danach über das Tray neu geöffnet werden."""
    token = secrets.token_urlsafe(32)
    path = token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fileutil.atomic_write_text(path, token)
    return token


def write_session(*, port: int, token: str, pid: int, home_key: str, started: datetime) -> None:
    path = session_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"port": int(port), "token": token, "pid": int(pid), "home_key": home_key,
            "started": started.isoformat(timespec="seconds")}
    fileutil.atomic_write_text(path, json.dumps(data, indent=2, ensure_ascii=False))


def read_session() -> dict | None:
    try:
        data = json.loads(session_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def remove_session(pid: int) -> None:
    """Löscht die Datei nur, wenn sie zu diesem Prozess gehört."""
    data = read_session()
    if data is None or data.get("pid") != pid:
        return
    try:
        session_path().unlink()
    except FileNotFoundError:
        pass
