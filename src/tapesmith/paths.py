"""Ablageorte für Laufzeitdaten (%APPDATA%\\Tapesmith, überschreibbar per TAPESMITH_HOME)."""

import os
import sys
from collections.abc import Mapping
from pathlib import Path

GUARD_MESSAGE = ("TAPESMITH_HOME fehlt: unter pytest ist der echte Datenordner %APPDATA%\\Tapesmith gesperrt. Tests und manuelle Aufrufe brauchen TAPESMITH_HOME=<eigener Temp-Ordner>.")


def _under_pytest() -> bool:
    return "PYTEST_CURRENT_TEST" in os.environ or "pytest" in sys.modules


def app_dir() -> Path:
    """Datenordner. Unter pytest ohne `TAPESMITH_HOME` gibt es keinen Rückfall auf
    %APPDATA%\\Tapesmith, sondern einen `RuntimeError` (Schutz der echten Nutzerdaten)."""
    base = os.environ.get("TAPESMITH_HOME")
    if not base:
        if _under_pytest():
            raise RuntimeError(GUARD_MESSAGE)
        appdata = os.environ.get("APPDATA", str(Path.home()))
        base = os.path.join(appdata, "Tapesmith")
        # Erster Start nach der Umbenennung: Daten aus %APPDATA%\P12Label einmalig kopieren.
        from tapesmith import migrate
        migrate.migrate_once(Path(appdata))
    path = Path(base)
    path.mkdir(parents=True, exist_ok=True)
    return path


def calibration_path() -> Path:
    return app_dir() / "calibration.json"


def capabilities_path() -> Path:
    return app_dir() / "capabilities.json"


def config_path() -> Path:
    return app_dir() / "config.json"


def log_dir() -> Path:
    path = app_dir() / "logs"
    path.mkdir(exist_ok=True)
    return path


def history_db_path() -> Path:
    return app_dir() / "history.sqlite3"


def child_env(env: Mapping[str, str] | None = None) -> dict[str, str]:
    """Umgebung für Kindprozesse: `env` (Default `os.environ`) plus ausdrücklich das aktuelle
    `TAPESMITH_HOME`, damit ein gestarteter Dienst oder ein Fenster nie in einen anderen
    Datenordner fällt. Ohne `TAPESMITH_HOME` greift die Sperre von `app_dir()` (unter pytest)."""
    result = dict(os.environ if env is None else env)
    home = os.environ.get("TAPESMITH_HOME")
    if home:
        result["TAPESMITH_HOME"] = home
    else:
        app_dir()
        result.pop("TAPESMITH_HOME", None)
    return result
