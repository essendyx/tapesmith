"""Spaltenzuordnung zu Vorlagenfeldern (automatisch + speicherbar), Zeilenauswahl und Filter."""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from tapesmith import paths
from tapesmith.dataimport.table import Table
from tapesmith.fileutil import FileLock, atomic_write_text
from tapesmith.i18n import _t


def _normalize(text: str) -> str:
    return text.casefold().replace(" ", "").replace("_", "").replace("-", "")


@dataclass(frozen=True)
class ColumnMapping:
    columns: dict[str, str]


def auto_map(headers: Sequence[str], fields: Sequence[tuple[str, str]]) -> ColumnMapping:
    if len(headers) == 1 and len(fields) == 1:
        return ColumnMapping(columns={fields[0][0]: headers[0]})
    norm_headers = {h: _normalize(h) for h in headers}
    used: set[str] = set()
    columns: dict[str, str] = {}
    for fid, fname in fields:
        norm_id = _normalize(fid)
        norm_name = _normalize(fname)
        match = ""
        for h in headers:
            if h in used:
                continue
            nh = norm_headers[h]
            if nh == norm_id or nh == norm_name:
                match = h
                break
        if match:
            used.add(match)
        columns[fid] = match
    return ColumnMapping(columns=columns)


class MappingStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else paths.app_dir() / "mappings.json"

    def _key(self, template: str, headers: Sequence[str]) -> str:
        return f"{template}|" + "|".join(h.casefold() for h in headers)

    def _load(self) -> dict:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, template: str, headers: Sequence[str], mapping: ColumnMapping) -> None:
        lock_path = self.path.with_name(self.path.name + ".lock")
        with FileLock(lock_path):
            data = self._load()
            data[self._key(template, headers)] = mapping.columns
            atomic_write_text(self.path, json.dumps(data, ensure_ascii=False, indent=2))

    def load(self, template: str, headers: Sequence[str]) -> ColumnMapping | None:
        data = self._load()
        key = self._key(template, headers)
        if key not in data:
            return None
        return ColumnMapping(columns=dict(data[key]))


def apply_mapping(table: Table, mapping: ColumnMapping, rows: Sequence[int] | None = None) -> list[dict[str, str]]:
    header_index = {h: i for i, h in enumerate(table.headers)}
    unknown = [col for col in mapping.columns.values() if col and col not in header_index]
    if unknown:
        raise ValueError(_t("Spalte '{value}' gibt es nicht (vorhanden: {items})", value=unknown[0], items=', '.join(table.headers)))
    indices = range(len(table.rows)) if rows is None else rows
    result = []
    for i in indices:
        row = table.rows[i]
        entry = {fid: row[header_index[col]] for fid, col in mapping.columns.items() if col}
        result.append(entry)
    return result


def filter_rows(table: Table, query: str, column: str | None = None) -> list[int]:
    if not query:
        return list(range(len(table.rows)))
    needle = query.casefold()
    if column is not None:
        idx = table.headers.index(column)
        return [i for i, row in enumerate(table.rows) if needle in row[idx].casefold()]
    return [i for i, row in enumerate(table.rows) if any(needle in cell.casefold() for cell in row)]


def parse_row_selection(text: str, total: int) -> list[int]:
    text = text.strip()
    if not text or text.casefold() == "alle":
        return list(range(total))
    selected: set[int] = set()
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_s, _, end_s = part.partition("-")
            start, end = int(start_s), int(end_s)
        else:
            start = end = int(part)
        if start < 1 or end > total or start > end:
            raise ValueError(_t("Zeile außerhalb des Bereichs 1-{total}: '{part}'", total=total, part=part))
        selected.update(range(start - 1, end))
    return sorted(selected)
