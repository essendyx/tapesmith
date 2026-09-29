"""Zentrale Nummernkreise: Reservieren, Verwerfen, Export/Import mit Dateisperre in einem
wählbaren Ordner (`numbering.dir`, z. B. Git-Repo oder Share), damit ein zweiter Rechner keine
Dubletten erzeugt. Vorlagen-Zähler können ebenfalls dort liegen (`counter_store(cfg)`).
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from tapesmith import config, paths
from tapesmith.fileutil import FileLock, atomic_write_text
from tapesmith.i18n import _t

FILE_NAME = "nummernkreise.json"

_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


def numbering_dir(cfg: dict) -> Path:
    """Setting `numbering.dir` (Umgebungsvariablen expandiert) oder `paths.app_dir()`; angelegt."""
    custom = config.setting(cfg, "numbering.dir")
    path = Path(os.path.expanduser(os.path.expandvars(custom))) if custom else paths.app_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path


def counter_store(cfg: dict):
    """`CounterStore` für Vorlagen-Zähler im zentralen Nummernkreis-Ordner (statt fest unter
    `app_dir()`), damit ein zweiter Rechner mit demselben `numbering.dir` keine Dubletten erzeugt."""
    from tapesmith.templates.fill import CounterStore  # spät importiert: vermeidet Zyklus

    return CounterStore(numbering_dir(cfg) / "counters.json")


@dataclass(frozen=True)
class NumberRange:
    key: str
    prefix: str
    width: int
    next: int
    voided: tuple[dict, ...] = ()

    def format(self, n: int) -> str:
        return self.prefix + str(n).zfill(self.width)


def _merge_voided(existing: list, incoming: list) -> list:
    merged = list(existing)
    seen = {(v.get("number"), v.get("reason"), v.get("at")) for v in existing}
    for entry in incoming:
        key = (entry.get("number"), entry.get("reason"), entry.get("at"))
        if key not in seen:
            merged.append(entry)
            seen.add(key)
    return merged


class NumberRanges:
    def __init__(self, path: Path | None = None, *, clock: Callable[[], datetime] = datetime.now):
        if path is not None:
            self.path = Path(path)
        else:
            try:
                cfg = config.load_config()
                self.path = numbering_dir(cfg) / FILE_NAME
            except (ValueError, OSError, json.JSONDecodeError):
                self.path = paths.app_dir() / FILE_NAME
        self._clock = clock
        self._lock_path = self.path.with_name(self.path.name + ".lock")

    def _load(self) -> dict:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(self.path, json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True))

    def _to_range(self, key: str, raw: dict) -> NumberRange:
        return NumberRange(key=key, prefix=raw.get("prefix", ""), width=raw.get("width", 0),
                            next=raw.get("next", 1), voided=tuple(raw.get("voided", [])))

    def define(self, key: str, *, start: int = 1, prefix: str = "", width: int = 0) -> NumberRange:
        if not _KEY_RE.match(key):
            raise ValueError(_t("Ungültiger Schlüssel {key!r} (erlaubt: A-Z a-z 0-9 _ - , 1..32 Zeichen)", key=key))
        if start < 0:
            raise ValueError(_t("'start' muss ≥ 0 sein, ist {start}", start=start))
        if not 0 <= width <= 12:
            raise ValueError(_t("'width' muss 0..12 sein, ist {width}", width=width))
        with FileLock(self._lock_path):
            data = self._load()
            if key in data:
                raise ValueError(_t("Nummernkreis {key!r} existiert bereits", key=key))
            raw = {"prefix": prefix, "width": width, "next": start, "start": start, "voided": []}
            data[key] = raw
            self._save(data)
            return self._to_range(key, raw)

    def get(self, key: str) -> NumberRange:
        data = self._load()
        if key not in data:
            raise KeyError(key)
        return self._to_range(key, data[key])

    def list(self) -> list[NumberRange]:
        data = self._load()
        return [self._to_range(k, v) for k, v in sorted(data.items())]

    def peek(self, key: str) -> str:
        r = self.get(key)
        return r.format(r.next)

    def reserve(self, key: str, count: int = 1) -> list[str]:
        if not 1 <= count <= 500:
            raise ValueError(_t("'count' muss 1..500 sein, ist {count}", count=count))
        with FileLock(self._lock_path):
            data = self._load()
            if key not in data:
                raise KeyError(key)
            r = self._to_range(key, data[key])
            numbers = [r.format(r.next + i) for i in range(count)]
            raw = dict(data[key])
            raw["next"] = r.next + count
            data[key] = raw
            self._save(data)
            return numbers

    def advance_to(self, key: str, n: int) -> NumberRange:
        """Hebt `next` auf `max(next, n)` an (senkt nie). Kreis fehlt: `KeyError(key)`."""
        with FileLock(self._lock_path):
            data = self._load()
            if key not in data:
                raise KeyError(key)
            raw = dict(data[key])
            if n > raw.get("next", 1):
                raw["next"] = n
                data[key] = raw
                self._save(data)
            return self._to_range(key, raw)

    def void(self, key: str, number: str, reason: str) -> None:
        if not reason or not reason.strip():
            raise ValueError(_t("Grund darf nicht leer sein"))
        with FileLock(self._lock_path):
            data = self._load()
            if key not in data:
                raise KeyError(key)
            raw = data[key]
            r = self._to_range(key, raw)
            start = raw.get("start", 1)
            if not number.startswith(r.prefix):
                raise ValueError(_t("Nummer {number!r} passt nicht zu Präfix {prefix!r}", number=number, prefix=r.prefix))
            rest = number[len(r.prefix):]
            if not rest.isdigit():
                raise ValueError(_t("Nummer {number!r} ungültig", number=number))
            n = int(rest)
            if not (start <= n < r.next):
                raise ValueError(_t("Nummer {number!r} wurde nie vergeben", number=number))
            entry = {"number": number, "reason": reason, "at": self._clock().isoformat(timespec="seconds")}
            raw = dict(raw)
            raw["voided"] = list(raw.get("voided", [])) + [entry]
            data[key] = raw
            self._save(data)

    def export_json(self, path: Path) -> None:
        with FileLock(self._lock_path):
            data = self._load()
        atomic_write_text(Path(path), json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True))

    def import_json(self, path: Path) -> list[str]:
        incoming = json.loads(Path(path).read_text(encoding="utf-8"))
        changes: list[str] = []
        with FileLock(self._lock_path):
            data = self._load()

            # Erst prüfen (nichts wird geschrieben, wenn irgendetwas nicht passt) …
            for key, raw_in in incoming.items():
                if key in data:
                    existing = data[key]
                    if (existing.get("prefix", "") != raw_in.get("prefix", "")
                            or existing.get("width", 0) != raw_in.get("width", 0)):
                        raise ValueError(
                            _t("Nummernkreis {key!r}: Präfix/Breite weicht vom vorhandenen Stand ab", key=key))

            # … dann anwenden.
            for key, raw_in in incoming.items():
                if key not in data:
                    raw = dict(raw_in)
                    raw.setdefault("start", raw_in.get("next", 1))
                    raw.setdefault("voided", [])
                    data[key] = raw
                    changes.append(_t("{key}: neu übernommen (weiter bei {next})", key=key, next=raw['next']))
                    continue
                existing = data[key]
                old_next = existing.get("next", 1)
                new_next = max(old_next, raw_in.get("next", 1))
                merged_voided = _merge_voided(existing.get("voided", []), raw_in.get("voided", []))
                updated = dict(existing)
                updated["next"] = new_next
                updated["voided"] = merged_voided
                data[key] = updated
                if new_next != old_next or len(merged_voided) != len(existing.get("voided", [])):
                    changes.append(f"{key}: next {old_next} → {new_next}")
                else:
                    changes.append(_t("{key}: unverändert", key=key))

            self._save(data)
        return changes
