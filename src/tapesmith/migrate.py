"""Einmalige Datenübernahme vom früheren App-Namen "P12 Label" (bis 0.2.x).

Beim ersten Start von Tapesmith gilt: existiert `%APPDATA%\\P12Label` und `%APPDATA%\\Tapesmith`
noch nicht, werden die Daten einmalig **kopiert** (nie verschoben, nie gelöscht). Das Original
bleibt als Sicherung liegen. Vorlagen mit der alten Endung `.p12label.json` bekommen in der Kopie
die neue Endung `.tapesmith.json`. In der kopierten config.json schaltet die Übernahme die Module ein,
zu denen Daten oder Einstellungen vorhanden sind (`modules.detect_used_modules`, im Zweifel alle), damit
nach dem Umstieg alles wie gewohnt da ist. Das Ergebnis steht in `logs/migration.log` im neuen Ordner.

Mit gesetztem `TAPESMITH_HOME` (bzw. `P12LABEL_HOME`) findet keine Übernahme statt: dann ist der
Datenordner ausdrücklich vorgegeben."""

from __future__ import annotations

import json
import logging
import os
import shutil
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from tapesmith.i18n import _t

LEGACY_DIR_NAME = "P12Label"
DIR_NAME = "Tapesmith"
LEGACY_TEMPLATE_SUFFIX = ".p12label.json"
TEMPLATE_SUFFIX = ".tapesmith.json"
LOG_NAME = "migration.log"

log = logging.getLogger("tapesmith.migrate")


def _rename_templates(folder: Path) -> int:
    templates = folder / "templates"
    if not templates.is_dir():
        return 0
    count = 0
    for file in sorted(templates.glob(f"*{LEGACY_TEMPLATE_SUFFIX}")):
        new = file.with_name(file.name[: -len(LEGACY_TEMPLATE_SUFFIX)] + TEMPLATE_SUFFIX)
        if not new.exists():
            file.rename(new)
            count += 1
    return count


def _enable_used_modules(folder: Path) -> tuple[str, ...] | None:
    """Setzt `modules.enabled` in `<folder>/config.json` auf die benutzten Module, falls die Datei
    noch keine Modulliste hat. Rückgabe: die gesetzte Liste oder None (nichts geändert)."""
    from tapesmith import modules  # spät: dieses Modul wird schon beim Ermitteln des Datenordners geladen

    path = folder / "config.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig")) if path.is_file() else {}
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or "modules" in data:
        return None
    enabled = modules.detect_used_modules(folder)
    data["modules"] = {"enabled": list(enabled)}
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return enabled


def _write_log(target: Path, text: str, now: Callable[[], datetime]) -> None:
    try:
        logs = target / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        with (logs / LOG_NAME).open("a", encoding="utf-8") as fh:
            fh.write(f"{now():%Y-%m-%d %H:%M:%S} {text}\n")
    except OSError:
        pass


def migrate_legacy_data(legacy: Path, target: Path, *,
                        now: Callable[[], datetime] = datetime.now) -> bool:
    """Kopiert `legacy` nach `target`, wenn `legacy` ein Ordner ist und `target` noch fehlt.
    `True`, wenn dieser Aufruf die Daten übernommen hat. Fehler hinterlassen kein halbes
    `target`: kopiert wird in einen eigenen Zwischenordner, der erst am Ende umbenannt wird
    (laufen zwei Prozesse gleichzeitig los, gewinnt der erste, der zweite verwirft seine Kopie)."""
    legacy = Path(legacy)
    target = Path(target)
    if target.exists() or not legacy.is_dir():
        return False
    staging = target.with_name(f"{target.name}.migrating-{os.getpid()}")
    try:
        if staging.exists():
            shutil.rmtree(staging)
        shutil.copytree(legacy, staging)
        renamed = _rename_templates(staging)
        enabled = _enable_used_modules(staging)
        try:
            os.rename(staging, target)
        except OSError:
            shutil.rmtree(staging, ignore_errors=True)
            return False
    except OSError as exc:
        shutil.rmtree(staging, ignore_errors=True)
        log.warning("Datenübernahme aus %s fehlgeschlagen: %s", legacy, exc)
        return False
    text = (_t("Daten aus {legacy} übernommen (kopiert, das Original bleibt unverändert); Vorlagen auf {template_suffix} umbenannt: {renamed}", legacy=legacy, template_suffix=TEMPLATE_SUFFIX, renamed=renamed))
    if enabled is not None:
        text += _t("; Module eingeschaltet: {value}", value=', '.join(enabled) or 'keine')
    _write_log(target, text, now)
    log.info(text)
    return True


_done = False


def migrate_once(appdata: Path) -> bool:
    """Einmal pro Prozess: `<appdata>\\P12Label` nach `<appdata>\\Tapesmith` übernehmen."""
    global _done
    if _done:
        return False
    _done = True
    return migrate_legacy_data(Path(appdata) / LEGACY_DIR_NAME, Path(appdata) / DIR_NAME)
