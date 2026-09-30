"""Sicherung der Zustandsdaten: Zip mit allen Zustandsdateien inkl. SQLite (konsistent über
`sqlite3.Connection.backup`), Wiederherstellen, Aufbewahrung, optional täglich automatisch (der
Dienst ruft `maybe_auto_backup`)."""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import tempfile
import zipfile
from collections.abc import Callable
from datetime import datetime
from pathlib import Path, PurePosixPath, PureWindowsPath

from tapesmith import __version__, config, fileutil, paths
from tapesmith.i18n import _t

STATE_FILES = ("config.json", "calibration.json", "capabilities.json", "counters.json", "rolls.json",
               "mappings.json", "tapes.json", "targets.json", "nummernkreise.json")
STATE_DBS = ("history.sqlite3", "queue.sqlite3", "inventory.sqlite3")
STATE_DIRS = ("templates", "icons")
BACKUP_PREFIX = "tapesmith-backup-"
MANIFEST_FORMAT = "tapesmith-backup"
MANIFEST_VERSION = 1


def backup_dir(cfg: dict | None = None) -> Path:
    """Setting `backup.dir` oder `app_dir()/"backups"` (angelegt)."""
    cfg = cfg if cfg is not None else {}
    custom = config.setting(cfg, "backup.dir")
    path = Path(os.path.expandvars(custom)) if custom else paths.app_dir() / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _backup_sqlite_into_zip(zf: zipfile.ZipFile, src: Path, name: str) -> None:
    """Konsistente Kopie über die SQLite-Backup-API (auch bei offener WAL-Verbindung); die
    Kopie wird über eine temporäre Datei in den Zip-Stream geschrieben, beide Verbindungen
    werden anschließend geschlossen."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir) / name
        src_conn = sqlite3.connect(str(src))
        dst_conn = sqlite3.connect(str(tmp_path))
        try:
            src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
            src_conn.close()
        zf.write(tmp_path, name)


def _files_in_dir(src_dir: Path, arc_prefix: str) -> list[tuple[Path, str]]:
    return [
        (file, f"{arc_prefix}/{file.relative_to(src_dir).as_posix()}")
        for file in sorted(src_dir.rglob("*")) if file.is_file()
    ]


def create_backup(target_dir: Path | None = None, *, now: datetime | None = None, keep: int | None = None,
                   cfg: dict | None = None) -> Path:
    """Schreibt `<BACKUP_PREFIX><Zeitstempel>.zip` in `target_dir` (Default `backup_dir(cfg)`) und
    behält danach nur die neuesten `keep` Sicherungen im Ordner."""
    cfg = cfg if cfg is not None else {}
    now = now or datetime.now()
    target = Path(target_dir) if target_dir is not None else backup_dir(cfg)
    target.mkdir(parents=True, exist_ok=True)
    keep = keep if keep is not None else config.setting(cfg, "backup.keep")

    zip_path = target / f"{BACKUP_PREFIX}{now.strftime('%Y%m%d-%H%M%S')}.zip"
    app = paths.app_dir()
    manifest_files: list[str] = []

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in STATE_FILES:
            src = app / name
            if src.exists():
                zf.write(src, name)
                manifest_files.append(name)

        for name in STATE_DBS:
            src = app / name
            if src.exists():
                _backup_sqlite_into_zip(zf, src, name)
                manifest_files.append(name)

        for dirname in STATE_DIRS:
            src_dir = app / dirname
            if src_dir.exists():
                for file, arcname in _files_in_dir(src_dir, dirname):
                    zf.write(file, arcname)
                    manifest_files.append(arcname)

        numbering_custom = config.setting(cfg, "numbering.dir")
        if numbering_custom:
            ndir = Path(os.path.expandvars(numbering_custom))
            for fname in ("nummernkreise.json", "counters.json"):
                src = ndir / fname
                if src.exists():
                    arcname = f"numbering/{fname}"
                    zf.write(src, arcname)
                    manifest_files.append(arcname)

        manifest = {
            "format": MANIFEST_FORMAT,
            "version": MANIFEST_VERSION,
            "app_version": __version__,
            "created": now.isoformat(timespec="seconds"),
            "files": manifest_files,
        }
        zf.writestr("MANIFEST.json", json.dumps(manifest, indent=2, ensure_ascii=False))

    _apply_retention(target, keep)
    return zip_path


def _apply_retention(directory: Path, keep: int) -> None:
    for path, _created, _size in list_backups(directory)[keep:]:
        path.unlink()


def list_backups(directory: Path | None = None) -> list[tuple[Path, datetime, int]]:
    """Neueste zuerst."""
    directory = Path(directory) if directory is not None else backup_dir()
    items: list[tuple[Path, datetime, int]] = []
    for path in directory.glob(f"{BACKUP_PREFIX}*.zip"):
        stamp = path.stem[len(BACKUP_PREFIX):]
        try:
            created = datetime.strptime(stamp, "%Y%m%d-%H%M%S")
        except ValueError:
            continue
        items.append((path, created, path.stat().st_size))
    items.sort(key=lambda item: item[1], reverse=True)
    return items


_DRIVE_LETTER_RE = re.compile(r"^[A-Za-z]:")


def _check_zip_slip(names: list[str]) -> None:
    """Weist Zip-Member zurück, die außerhalb des Zielordners landen könnten.

    `PurePosixPath` allein reicht nicht: es kennt nur '/' als Trennzeichen, sodass ein
    Windows-Pfad mit Backslashes (z. B. "..\\..\\evil.txt") oder ein Laufwerksbuchstabe
    (z. B. "C:\\Windows\\evil.txt") unerkannt bliebe: `pathlib` interpretiert Backslashes
    auf Windows als Trennzeichen, und ein absoluter rechter Operand verwirft beim Verbinden
    mit `/` den linken Teil komplett. Daher: Backslashes und Laufwerksbuchstaben explizit
    zurückweisen, zusätzlich zur '..'/absolut-Prüfung über PurePosixPath und PureWindowsPath.
    """
    for name in names:
        if name == "MANIFEST.json":
            continue
        if "\\" in name or _DRIVE_LETTER_RE.match(name):
            raise ValueError(_t("Zip enthält unsicheren Pfad: {name}", name=name))
        posix = PurePosixPath(name)
        parts = posix.parts
        if (posix.is_absolute() or PureWindowsPath(name).is_absolute()
                or not parts or ".." in parts or any(p.endswith(":") for p in parts)):
            raise ValueError(_t("Zip enthält unsicheren Pfad: {name}", name=name))


def restore_backup(archive: Path, *, dry_run: bool = False,
                    running_check: Callable[[], bool] | None = None,
                    now: datetime | None = None) -> list[str]:
    """Stellt eine Sicherung wieder her. `numbering/…` wird NICHT automatisch zurückgeschrieben
    (zentraler Ordner); die Rückgabe nennt das als Hinweis."""
    archive = Path(archive)
    now = now or datetime.now()
    if running_check is not None and running_check():
        raise ValueError(_t("Druckdienst läuft, erst `tapesmith daemon stop`"))

    with zipfile.ZipFile(archive, "r") as zf:
        names = zf.namelist()
        _check_zip_slip(names)
        if "MANIFEST.json" not in names:
            raise ValueError(_t("{archive}: MANIFEST.json fehlt", archive=archive))
        manifest = json.loads(zf.read("MANIFEST.json").decode("utf-8"))
        if manifest.get("format") != MANIFEST_FORMAT:
            raise ValueError(_t("{archive}: unbekanntes Format {get!r}", archive=archive, get=manifest.get('format')))
        version = manifest.get("version")
        if not isinstance(version, int) or version > MANIFEST_VERSION:
            raise ValueError(_t("{archive}: Version {version!r} wird nicht unterstützt", archive=archive, version=version))

        app = paths.app_dir()
        member_names = [n for n in names if n != "MANIFEST.json"]
        restored: list[str] = []
        notes: list[str] = []

        if dry_run:
            for name in member_names:
                if name.startswith("numbering/"):
                    notes.append(_t("{name}: zentraler Ordner, wird nicht automatisch zurückgeschrieben", name=name))
                else:
                    restored.append(name)
            return restored + notes

        backup_before = app / "backups" / f"vor-restore-{now.strftime('%Y%m%d-%H%M%S')}"
        for name in member_names:
            if name.startswith("numbering/"):
                notes.append(_t("{name}: zentraler Ordner, wird nicht automatisch zurückgeschrieben", name=name))
                continue
            dest = app / name
            if dest.exists():
                backup_target = backup_before / name
                backup_target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(dest), str(backup_target))
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(name) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
            restored.append(name)
        return restored + notes


def backup_due(last: datetime | None, now: datetime) -> bool:
    if last is None:
        return True
    return last.date() < now.date()


def maybe_auto_backup(cfg: dict, now: datetime | None = None) -> Path | None:
    """Nur wenn `backup.auto_daily` gesetzt ist und die letzte Sicherung nicht mehr vom
    heutigen Tag ist (Marker `backup_dir(cfg)/".last_auto"`, ISO-Zeitstempel)."""
    now = now or datetime.now()
    if not config.setting(cfg, "backup.auto_daily"):
        return None
    marker = backup_dir(cfg) / ".last_auto"
    last = None
    if marker.exists():
        try:
            last = datetime.fromisoformat(marker.read_text(encoding="utf-8").strip())
        except ValueError:
            last = None
    if not backup_due(last, now):
        return None
    path = create_backup(cfg=cfg, now=now)
    fileutil.atomic_write_text(marker, now.isoformat(timespec="seconds"))
    return path
