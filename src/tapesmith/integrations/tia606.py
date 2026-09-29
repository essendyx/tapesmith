"""TIA-606-ID-Schema und Kabel-Register.

`generate` baut Port-IDs aus einem `str.format`-Muster (Standard `{rack}.U{unit:02}:P{port:02}`)
für Bereiche aus Rack, Höheneinheiten und Ports. `free_ids` reserviert stattdessen freie
fortlaufende IDs aus dem zentralen Nummernkreis `kabel`. `KabelRegister` kennt alle vergebenen
bzw. importierten Kabel-IDs (Datei `kabel.json` unter `settings.data_dir()`), mit Dateisperre wie
`numbering.NumberRanges`.
"""

from __future__ import annotations

import json
import re
import string
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from tapesmith.fileutil import FileLock, atomic_write_text
from tapesmith.numbering import NumberRanges
from tapesmith.i18n import _t

_RACK_RE = re.compile(r"^[A-Z0-9]{1,8}$")
_ALLOWED_FIELDS = {"rack", "unit", "port"}
_MAX_NUMBERS = 2000


@dataclass(frozen=True)
class PortRange:
    rack: str
    units: tuple[int, ...]
    ports: tuple[int, ...]

    def __post_init__(self) -> None:
        if not _RACK_RE.match(self.rack):
            raise ValueError(_t("Ungültiges Rack {rack!r} (erlaubt: A-Z 0-9, 1..8 Zeichen)", rack=self.rack))
        if not self.units:
            raise ValueError(_t("'units' darf nicht leer sein"))
        if not self.ports:
            raise ValueError(_t("'ports' darf nicht leer sein"))


def _parse_int(text: str) -> int:
    text = text.strip()
    try:
        value = int(text)
    except ValueError as exc:
        raise ValueError(_t("Ungültige Zahl {text!r}", text=text)) from exc
    if not 1 <= value <= 9999:
        raise ValueError(_t("Zahl {value} muss 1..9999 sein", value=value))
    return value


def parse_numbers(spec: str) -> tuple[int, ...]:
    """"1-24", "1,3,5-7" -> aufsteigende Werte 1..9999 in Reihenfolge des ersten Auftretens.

    Höchstens 2000 Werte; leer, ungültig oder ein Bereich mit Anfang > Ende: ValueError."""
    spec = spec.strip()
    if not spec:
        raise ValueError(_t("Zahlenbereich darf nicht leer sein"))
    result: list[int] = []
    seen: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_s, _, end_s = part.partition("-")
            start, end = _parse_int(start_s), _parse_int(end_s)
            if start > end:
                raise ValueError(_t("Ungültiger Bereich {part!r}: Anfang > Ende", part=part))
            values: Sequence[int] = range(start, end + 1)
        else:
            values = (_parse_int(part),)
        for value in values:
            if value not in seen:
                seen.add(value)
                result.append(value)
    if not result:
        raise ValueError(_t("Zahlenbereich darf nicht leer sein"))
    if len(result) > _MAX_NUMBERS:
        raise ValueError(_t("Zahlenbereich hat mehr als {max_numbers} Werte ({count})", max_numbers=_MAX_NUMBERS, count=len(result)))
    return tuple(result)


def _field_base(field_name: str) -> str:
    return field_name.split(".")[0].split("[")[0]


def render_id(pattern: str, *, rack: str, unit: int, port: int) -> str:
    """`str.format`-Muster mit den Namen rack, unit, port; andere Namen -> ValueError."""
    fields = {_field_base(name) for _, name, _, _ in string.Formatter().parse(pattern) if name is not None}
    unknown = fields - _ALLOWED_FIELDS
    if unknown:
        raise ValueError(
            _t("Unbekannte Platzhalter im Muster {pattern!r}: {items} (erlaubt: rack, unit, port)", pattern=pattern, items=', '.join(sorted(unknown))))
    try:
        return pattern.format(rack=rack, unit=unit, port=port)
    except (KeyError, IndexError, ValueError) as exc:
        raise ValueError(_t("Ungültiges Muster {pattern!r}: {exc}", pattern=pattern, exc=exc)) from exc


def generate(pattern: str, ranges: Sequence[PortRange]) -> list[str]:
    """IDs in der Reihenfolge Rack, Höheneinheit, Port; Dubletten im Ergebnis -> ValueError."""
    result: list[str] = []
    seen: set[str] = set()
    for port_range in ranges:
        for unit in port_range.units:
            for port in port_range.ports:
                new_id = render_id(pattern, rack=port_range.rack, unit=unit, port=port)
                key = new_id.casefold()
                if key in seen:
                    raise ValueError(_t("Doppelte Kabel-ID erzeugt: {new_id}", new_id=new_id))
                seen.add(key)
                result.append(new_id)
    return result


def free_ids(ranges: NumberRanges, data: dict, count: int) -> list[str]:
    """Reserviert `count` freie fortlaufende IDs aus dem Nummernkreis `kabel.range`.

    Fehlt der Kreis, wird er mit `kabel.prefix`/`kabel.width` angelegt (Start 1)."""
    from tapesmith.integrations import settings

    key = settings.setting(data, "kabel.range")
    try:
        ranges.get(key)
    except KeyError:
        ranges.define(key, start=1, prefix=settings.setting(data, "kabel.prefix"),
                      width=settings.setting(data, "kabel.width"))
    return ranges.reserve(key, count)


@dataclass(frozen=True)
class KabelEntry:
    id: str
    quelle: str
    ziel: str
    kabeltyp: str
    quelle_import: str
    created: str


class KabelRegister:
    """Alle vergebenen bzw. importierten Kabel-IDs, gesperrt und atomar geschrieben wie die Nummernkreise."""

    def __init__(self, path: Path | None = None, *, clock: Callable[[], datetime] = datetime.now):
        if path is not None:
            self.path = Path(path)
        else:
            from tapesmith.integrations import settings

            self.path = settings.data_dir() / "kabel.json"
        self._clock = clock
        self._lock_path = self.path.with_name(self.path.name + ".lock")

    def _load(self) -> dict:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self, data: dict) -> None:
        atomic_write_text(self.path, json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True))

    def _to_entry(self, raw: dict) -> KabelEntry:
        return KabelEntry(id=raw["id"], quelle=raw.get("quelle", ""), ziel=raw.get("ziel", ""),
                          kabeltyp=raw.get("kabeltyp", ""), quelle_import=raw.get("quelle_import", "manuell"),
                          created=raw.get("created", ""))

    def exists(self, kabel_id: str) -> bool:
        return kabel_id.casefold() in self._load()

    def get(self, kabel_id: str) -> KabelEntry | None:
        raw = self._load().get(kabel_id.casefold())
        return self._to_entry(raw) if raw is not None else None

    def all(self) -> list[KabelEntry]:
        data = self._load()
        return [self._to_entry(data[key]) for key in sorted(data)]

    def duplicates(self, ids: Sequence[str]) -> list[str]:
        """IDs, die im Register stehen oder in `ids` mehrfach vorkommen (Reihenfolge des ersten Auftretens)."""
        data = self._load()
        seen: set[str] = set()
        result: list[str] = []
        for kabel_id in ids:
            key = kabel_id.casefold()
            if key in data or key in seen:
                if kabel_id not in result:
                    result.append(kabel_id)
            seen.add(key)
        return result

    def add(self, entries: Sequence[KabelEntry], *, allow_existing: bool = False) -> None:
        with FileLock(self._lock_path):
            data = self._load()
            if not allow_existing:
                for entry in entries:
                    if entry.id.casefold() in data:
                        raise ValueError(_t("Kabel-ID bereits vergeben: {id}", id=entry.id))
            for entry in entries:
                data[entry.id.casefold()] = {
                    "id": entry.id, "quelle": entry.quelle, "ziel": entry.ziel,
                    "kabeltyp": entry.kabeltyp, "quelle_import": entry.quelle_import,
                    "created": entry.created,
                }
            self._save(data)

    def remove(self, kabel_id: str) -> bool:
        with FileLock(self._lock_path):
            data = self._load()
            key = kabel_id.casefold()
            if key not in data:
                return False
            del data[key]
            self._save(data)
            return True
