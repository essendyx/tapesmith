"""Cache des letzten SSH-Scans je Host (für Plattentausch und Plausibilitätsprüfung).

Ablage `<data_dir>/scans/<host>.json` als `{"host", "scanned_at", "disks": [...]}`; kaputte
Dateien gelten als nicht vorhanden.
"""

from __future__ import annotations

import dataclasses
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from tapesmith.fileutil import atomic_write_text
from tapesmith.integrations.settings import data_dir
from tapesmith.sshscan import DiskRow
from tapesmith.i18n import _t

HOST_RE = re.compile(r"^[A-Za-z0-9._-]{1,32}$")
_OPTIONAL = {f.name for f in dataclasses.fields(DiskRow) if "None" in str(f.type)}
_FIELDS = tuple(f.name for f in dataclasses.fields(DiskRow))


@dataclass(frozen=True)
class ScanRecord:
    host: str
    scanned_at: str                    # ISO ohne Zeitzone, Sekunden
    disks: tuple[DiskRow, ...]


def _check_host(host: str) -> str:
    if not isinstance(host, str) or not HOST_RE.match(host) or set(host) == {"."}:
        raise ValueError(_t("Ungültiger Hostname '{host}' (erlaubt: A-Z, a-z, 0-9, Punkt, Unterstrich, Bindestrich, bis 32 Zeichen)", host=host))
    return host


def _folder() -> Path:
    return data_dir() / "scans"


def _path(host: str) -> Path:
    return _folder() / f"{_check_host(host)}.json"


def save_scan(host: str, disks: Sequence[DiskRow], *, when: datetime | None = None) -> ScanRecord:
    """Speichert den Scan eines Hosts atomar und gibt den Datensatz zurück."""
    path = _path(host)
    scanned_at = (when or datetime.now()).isoformat(timespec="seconds")
    record = ScanRecord(host=host, scanned_at=scanned_at, disks=tuple(disks))
    payload = {"host": host, "scanned_at": scanned_at,
               "disks": [dataclasses.asdict(d) for d in record.disks]}
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return record


def _disk(entry: dict) -> DiskRow:
    values = {}
    for name in _FIELDS:
        value = entry.get(name)
        if value is None:
            value = None if name in _OPTIONAL else ""
        elif not isinstance(value, str):
            raise ValueError(_t("Feld {name} ist kein Text", name=name))
        values[name] = value
    return DiskRow(**values)


def load_scan(host: str) -> ScanRecord | None:
    """Letzter Scan eines Hosts oder None (fehlt oder kaputt)."""
    path = _path(host)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        scanned_at = data["scanned_at"]
        if not isinstance(scanned_at, str):
            return None
        disks = tuple(_disk(entry) for entry in data["disks"])
    except (OSError, UnicodeDecodeError, ValueError, KeyError, TypeError, AttributeError):
        return None
    return ScanRecord(host=host, scanned_at=scanned_at, disks=disks)


def all_scans() -> list[ScanRecord]:
    """Alle lesbaren Scans, nach Host sortiert."""
    folder = _folder()
    if not folder.is_dir():
        return []
    records = []
    for file in folder.glob("*.json"):
        try:
            record = load_scan(file.stem)
        except ValueError:
            continue
        if record is not None:
            records.append(record)
    return sorted(records, key=lambda r: r.host)
