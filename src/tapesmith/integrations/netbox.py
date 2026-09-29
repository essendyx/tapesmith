"""NetBox-CSV-Kabelexport einlesen, Spalten zuordnen und Zeilen für die Vorlage `kabelfahne`
(bzw. `kabelwickel`) aufbereiten.

Vergibt selbst keine IDs: fehlende Kabel-IDs kommen über den injizierbaren `new_id` (typischerweise
`tia606.free_ids`), damit eine reine Vorschau (Route `/kabel/netbox`) keine Nummern verbraucht.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from tapesmith.dataimport.mapping import ColumnMapping, MappingStore, auto_map
from tapesmith.dataimport.table import Table, _decode_bytes, read_csv
from tapesmith.integrations.tia606 import KabelRegister
from tapesmith.i18n import _t

MAPPING_KEY = "netbox-kabel"

FIELDS: tuple[tuple[str, str], ...] = (
    ("kabel_id", "Kabel-ID"), ("quelle", "Quelle"), ("ziel", "Ziel"),
    ("kabeltyp", "Kabeltyp"), ("farbe", "Farbe"), ("laenge", "Länge"),
)

SYNONYMS: dict[str, tuple[str, ...]] = {
    "kabel_id": ("Label", "Cable", "ID", "Kabel"),
    "quelle": ("Side A", "Termination A", "A Side", "Seite A", "Anschluss A"),
    "ziel": ("Side B", "Termination B", "B Side", "Seite B", "Anschluss B"),
    "kabeltyp": ("Type", "Typ"),
    "farbe": ("Color", "Farbe"),
    "laenge": ("Length", "Länge"),
}

_TYPE_MAP: dict[str, str] = {
    "cat6": "Cat6", "cat6a": "Cat6a",
    "dac-passive": "DAC", "dac-active": "DAC",
    "smf": "LWL", "mmf": "LWL", "smf-os2": "LWL", "mmf-om4": "LWL",
    "power": "Kaltgeräte",
}

_FIELD_IDS = tuple(fid for fid, _ in FIELDS)


@dataclass(frozen=True)
class CableRow:
    kabel_id: str
    quelle: str
    ziel: str
    kabeltyp: str
    farbe: str
    laenge: str
    neu: bool


@dataclass(frozen=True)
class ImportResult:
    headers: tuple[str, ...]
    mapping: dict[str, str | list[str]]
    rows: tuple[CableRow, ...]
    duplicates: tuple[str, ...]
    warnings: tuple[str, ...]


def read_export(data: bytes | str, *, source: str = "netbox.csv") -> Table:
    text = _decode_bytes(data, None) if isinstance(data, bytes) else data
    return read_csv(text, name=source)


def _normalize(text: str) -> str:
    return text.strip().casefold()


def _match_header(fid: str, label: str, headers: Sequence[str]) -> str | None:
    norm_headers = {_normalize(h): h for h in headers}
    for candidate in (fid, label, *SYNONYMS.get(fid, ())):
        found = norm_headers.get(_normalize(candidate))
        if found is not None:
            return found
    return None


def suggest_mapping(table: Table, store: MappingStore | None = None) -> dict[str, str | list[str]]:
    """Gespeicherte Zuordnung (falls vorhanden) hat Vorrang, sonst SYNONYME, sonst `auto_map`."""
    if store is not None:
        stored = store.load(MAPPING_KEY, table.headers)
        if stored is not None:
            result: dict[str, str | list[str]] = {}
            for fid, col in stored.columns.items():
                if not col:
                    continue
                result[fid] = col.split("+") if "+" in col else col
            return result

    mapping: dict[str, str | list[str]] = {}
    for fid, label in FIELDS:
        header = _match_header(fid, label, table.headers)
        if header:
            mapping[fid] = header
    if len(mapping) < len(FIELDS):
        auto = auto_map(table.headers, FIELDS)
        for fid, col in auto.columns.items():
            if fid not in mapping and col:
                mapping[fid] = col
    return mapping


def combine_side(device: str, termination: str) -> str:
    """"SW1" + "P12" -> "SW1/P12"; ist nur eines gesetzt, nur dieses."""
    device = (device or "").strip()
    termination = (termination or "").strip()
    if device and termination:
        return f"{device}/{termination}"
    return device or termination


def _map_kabeltyp(value: str, kabeltyp_map: Mapping[str, str] | None) -> str:
    if not value:
        return value
    table = dict(_TYPE_MAP)
    if kabeltyp_map:
        table.update(kabeltyp_map)
    return table.get(value.strip().lower(), value)


def _cell(row: tuple[str, ...], header_index: Mapping[str, int], col: str | Sequence[str] | None) -> str:
    if not col:
        return ""
    if isinstance(col, str):
        return row[header_index[col]] if col in header_index else ""
    values = [row[header_index[c]] for c in col if c in header_index]
    if len(values) >= 2:
        return combine_side(values[0], values[1])
    return values[0] if values else ""


def build_rows(table: Table, mapping: Mapping[str, str | Sequence[str]], *, register: KabelRegister,
               new_id: Callable[[int], list[str]] | None = None,
               kabeltyp_map: Mapping[str, str] | None = None) -> ImportResult:
    header_index = {h: i for i, h in enumerate(table.headers)}
    raw_rows = [
        {fid: _cell(row, header_index, mapping.get(fid)) for fid in _FIELD_IDS}
        for row in table.rows
    ]

    missing = [i for i, entry in enumerate(raw_rows) if not entry["kabel_id"].strip()]
    assigned: dict[int, str] = {}
    warnings: list[str] = []
    if missing:
        if new_id is not None:
            for i, kabel_id in zip(missing, new_id(len(missing)), strict=True):
                assigned[i] = kabel_id
        else:
            for i in missing:
                warnings.append(_t("Zeile {value}: keine Kabel-ID (Vorlage vergibt keine neuen IDs)", value=i + 2))

    rows: list[CableRow] = []
    all_ids: list[str] = []
    for i, entry in enumerate(raw_rows):
        kabel_id = entry["kabel_id"].strip()
        neu = False
        if not kabel_id and i in assigned:
            kabel_id = assigned[i]
            neu = True
        rows.append(CableRow(kabel_id=kabel_id, quelle=entry["quelle"], ziel=entry["ziel"],
                             kabeltyp=_map_kabeltyp(entry["kabeltyp"], kabeltyp_map),
                             farbe=entry["farbe"], laenge=entry["laenge"], neu=neu))
        if kabel_id:
            all_ids.append(kabel_id)

    duplicates = tuple(register.duplicates(all_ids))
    return ImportResult(headers=table.headers, mapping=dict(mapping), rows=tuple(rows),
                        duplicates=duplicates, warnings=tuple(warnings))


def template_rows(rows: Sequence[CableRow]) -> tuple[list[str], list[list[str]]]:
    headers = ["kabel_id", "quelle", "ziel", "kabeltyp"]
    body = [[row.kabel_id, row.quelle, row.ziel, row.kabeltyp] for row in rows]
    return headers, body


def save_mapping(store: MappingStore, table: Table, mapping: Mapping[str, str | Sequence[str]]) -> None:
    columns: dict[str, str] = {}
    for fid, col in mapping.items():
        if isinstance(col, str):
            if col:
                columns[fid] = col
        elif col:
            columns[fid] = "+".join(col)
    store.save(MAPPING_KEY, table.headers, ColumnMapping(columns=columns))
