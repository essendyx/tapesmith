"""Protokolldateien im Ordner `logs` für die Seite „Protokoll“ der Web-Oberfläche.

Erlaubt sind nur Dateien direkt in `paths.log_dir()` mit Namen der Form `<name>.log` oder
`<name>.log.<n>` (rotierte Stände); Pfade, Unterordner und Verknüpfungen werden abgelehnt. Gelesen
wird vom Dateiende her, große Dateien werden nie ganz geladen. Ausgaben laufen durch
`support.mask_text`, Tokens und Passwörter erscheinen also nicht im Browser.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from tapesmith import paths
from tapesmith.i18n import _t

DAEMON_LOG_NAME = "daemon.log"
LEGACY_DAEMON_LOG_NAME = "p12d.log"

LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
_LEVEL_RANK = {name: rank for rank, name in enumerate(LEVELS)}
_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}\.log(\.\d{1,2})?$")
_LEVEL_RE = re.compile(r"\b(DEBUG|INFO|WARNING|ERROR|CRITICAL)\b")
_RECORD_START_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}")

MAX_LINES = 5000
DEFAULT_LINES = 500
# Beim Filtern (Stufe, Suche) höchstens so viel vom Dateiende lesen.
MAX_SCAN_BYTES = 8 * 1024 * 1024
_BLOCK = 64 * 1024


class LogNotFound(LookupError):
    """Unbekannte oder nicht erlaubte Protokolldatei."""


def daemon_log_path() -> Path:
    """Protokoll des Druckdienstes."""
    return paths.log_dir() / DAEMON_LOG_NAME


def migrate_legacy_daemon_log(log_dir: Path | None = None) -> bool:
    """Benennt `p12d.log` (samt rotierten Ständen) einmalig in `daemon.log` um, solange es noch
    kein `daemon.log` gibt. True, wenn etwas umbenannt wurde."""
    folder = paths.log_dir() if log_dir is None else Path(log_dir)
    new = folder / DAEMON_LOG_NAME
    if new.exists():
        return False
    moved = False
    for old in sorted(folder.glob(f"{LEGACY_DAEMON_LOG_NAME}*")):
        suffix = old.name[len(LEGACY_DAEMON_LOG_NAME):]
        if suffix and not re.fullmatch(r"\.\d{1,2}", suffix):
            continue
        try:
            old.rename(folder / f"{DAEMON_LOG_NAME}{suffix}")
            moved = True
        except OSError:
            pass
    return moved


def _allowed(folder: Path, name: str) -> Path:
    if not isinstance(name, str) or not _NAME_RE.fullmatch(name):
        raise LogNotFound(name)
    path = folder / name
    try:
        if path.is_symlink() or not path.is_file() or path.resolve().parent != folder.resolve():
            raise LogNotFound(name)
    except OSError as exc:
        raise LogNotFound(name) from exc
    return path


def list_logs(log_dir: Path | None = None) -> list[dict]:
    """Protokolldateien mit Name, Größe (Bytes) und Änderungszeit (Unix-Sekunden), neueste zuerst."""
    folder = paths.log_dir() if log_dir is None else Path(log_dir)
    result = []
    for entry in os.scandir(folder):
        if not _NAME_RE.fullmatch(entry.name) or entry.is_symlink() or not entry.is_file():
            continue
        stat = entry.stat()
        result.append({"name": entry.name, "size": stat.st_size, "mtime": stat.st_mtime})
    result.sort(key=lambda item: (-item["mtime"], item["name"]))
    return result


def _tail_bytes(path: Path, *, max_lines: int | None, max_bytes: int) -> tuple[bytes, bool]:
    """Letzte Zeilen der Datei als Bytes; `True`, wenn der Anfang der Datei fehlt."""
    with open(path, "rb") as handle:
        handle.seek(0, os.SEEK_END)
        end = handle.tell()
        pos = end
        chunks: list[bytes] = []
        newlines = 0
        while pos > 0 and end - pos < max_bytes:
            step = min(_BLOCK, pos, max_bytes - (end - pos))
            pos -= step
            handle.seek(pos)
            chunk = handle.read(step)
            chunks.append(chunk)
            newlines += chunk.count(b"\n")
            if max_lines is not None and newlines > max_lines:
                break
    data = b"".join(reversed(chunks))
    truncated = pos > 0
    if truncated:
        # angeschnittene erste Zeile verwerfen
        cut = data.find(b"\n")
        data = data[cut + 1:] if cut >= 0 else b""
    return data, truncated


def _records(text: str) -> list[dict]:
    """Zeilen mit Stufe; Folgezeilen ohne Zeitstempel (Tracebacks) erben die Stufe davor."""
    lines = []
    level = None
    for raw in text.splitlines():
        if _RECORD_START_RE.match(raw):
            match = _LEVEL_RE.search(raw[:80])
            level = match.group(1) if match else None
        lines.append({"text": raw, "level": level})
    return lines


def read_log(name: str, *, lines: int = DEFAULT_LINES, level: str | None = None, search: str | None = None,
             log_dir: Path | None = None) -> dict:
    """Die letzten `lines` Zeilen von `name`, optional ab Stufe `level` und mit `search` (ohne
    Groß/Klein). Ohne Filter wird nur so viel gelesen, wie für die Zeilen nötig ist."""
    from tapesmith.support import mask_text

    folder = paths.log_dir() if log_dir is None else Path(log_dir)
    path = _allowed(folder, name)
    lines = max(1, min(int(lines), MAX_LINES))
    if level is not None and level not in _LEVEL_RANK:
        raise ValueError(_t("Unbekannte Stufe '{level}' (erlaubt: {items})", level=level, items=", ".join(LEVELS)))
    needle = (search or "").strip().casefold()
    filtering = level is not None or bool(needle)
    data, truncated = _tail_bytes(path, max_lines=None if filtering else lines, max_bytes=MAX_SCAN_BYTES)
    records = _records(mask_text(data.decode("utf-8", errors="replace")))
    if level is not None:
        minimum = _LEVEL_RANK[level]
        records = [r for r in records if r["level"] is not None and _LEVEL_RANK[r["level"]] >= minimum]
    if needle:
        records = [r for r in records if needle in r["text"].casefold()]
    shown = records[-lines:]
    stat = path.stat()
    return {"name": path.name, "size": stat.st_size, "mtime": stat.st_mtime, "lines": shown,
            "truncated": truncated or len(records) > len(shown)}


def download_text(name: str, log_dir: Path | None = None) -> str:
    """Inhalt einer erlaubten Protokolldatei zum Herunterladen (maskiert, höchstens die letzten
    `MAX_SCAN_BYTES`); sonst `LogNotFound`."""
    from tapesmith.support import mask_text

    folder = paths.log_dir() if log_dir is None else Path(log_dir)
    data, _truncated = _tail_bytes(_allowed(folder, name), max_lines=None, max_bytes=MAX_SCAN_BYTES)
    return mask_text(data.decode("utf-8", errors="replace"))
