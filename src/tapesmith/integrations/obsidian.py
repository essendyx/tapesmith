"""Obsidian-Vault als Datenquelle und Rückkanal über den MCP-Server.

Notizen werden über die MCP-Werkzeuge `vault_list`, `vault_read`, `vault_search`, `vault_append`,
`vault_write` und `changelog_add` gelesen bzw. geschrieben. Die Ordnerfreigabe sitzt im
`VaultClient`: jeder pfadbezogene Aufruf prüft vorher `validate_note_path(path, self.folders)`.
Aus einer Notiz entstehen Label-Werte (Frontmatter, dann fette Aufzählungsschlüssel, dann
abgeleitete Werte) und Tabellen für den Seriendruck.

Ist der MCP-Server nicht erreichbar und `obsidian.vault_dir` gesetzt, lesen `list_notes`, `read` und
`note` (samt Frontmatter) die Markdown-Dateien direkt aus dem lokalen Vault-Ordner. Die
Ordnerfreigabe gilt dabei genauso; Schreiben (Vermerk, Changelog) geht nur über den MCP-Server.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from tapesmith.integrations.errors import NotConfigured, NotReachable
from tapesmith.integrations.frontmatter import (MdTable, bold_bullets, first_heading, normalize_key,
                                               split_frontmatter, tables)
from tapesmith.integrations.mcpclient import McpClient
from tapesmith.i18n import _t

SERVICE = "Obsidian"
IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
ALWAYS_ALLOWED: tuple[str, ...] = ("Assets",)
MAX_PATH_LEN = 200

_DRIVE_RE = re.compile(r"^[A-Za-z]:")
_NUMBER_RE = re.compile(r"\d+")
_HIT_MD_RE = re.compile(r"^(?P<path>.+?\.md):(?P<line>\d+)[:-](?P<text>.*)$", re.IGNORECASE)
_HIT_SLASH_RE = re.compile(r"^(?P<path>[^:\s][^:]*/[^:]*?):(?P<line>\d+)[:-](?P<text>.*)$")
_GROUPED_HIT_RE = re.compile(r"^\s+L?(?P<line>\d+)\s*[:-]\s?(?P<text>.*)$")
_TITLE_SEPARATORS = (" · ", "\u2014")


@dataclass(frozen=True)
class VaultHit:
    path: str
    line: int | None
    text: str


@dataclass(frozen=True)
class Note:
    path: str
    title: str
    text: str
    values: dict[str, str]
    tables: tuple[MdTable, ...]


def allowed_folders(data: dict) -> list[str]:
    """`obsidian.folders` plus `ALWAYS_ALLOWED`, Reihenfolge erhalten, ohne Dubletten."""
    result: list[str] = []
    for folder in [*(data.get("obsidian", {}).get("folders") or []), *ALWAYS_ALLOWED]:
        name = str(folder).strip().strip("/")
        if name and name.lower() not in (f.lower() for f in result):
            result.append(name)
    return result


def validate_note_path(path: str, folders: Sequence[str] | None = None) -> str:
    """Prüft einen Notizpfad und gibt ihn normalisiert zurück (`/` als Trenner, ohne `.md`)."""
    raw = str(path).strip()
    if not raw:
        raise ValueError(_t("Notizpfad fehlt"))
    if len(raw) > MAX_PATH_LEN:
        raise ValueError(_t("Notizpfad ist länger als {max_path_len} Zeichen", max_path_len=MAX_PATH_LEN))
    if raw[0] in "/\\":
        raise ValueError(_t("Ungültiger Notizpfad '{raw}': relativ zum Vault angeben, ohne führenden Schrägstrich", raw=raw))
    if _DRIVE_RE.match(raw):
        raise ValueError(_t("Ungültiger Notizpfad '{raw}': keine Laufwerksangabe", raw=raw))
    parts = re.split(r"[\\/]", raw)
    if any(part.strip() == ".." for part in parts):
        raise ValueError(_t("Ungültiger Notizpfad '{raw}': '..' ist nicht erlaubt", raw=raw))
    normalized = raw.replace("\\", "/").rstrip("/")
    if normalized.lower().endswith(".md"):
        normalized = normalized[:-3]
    if not normalized:
        raise ValueError(_t("Notizpfad fehlt"))
    if folders is not None:
        first = normalized.split("/", 1)[0].lower()
        if first not in (f.lower() for f in folders):
            raise ValueError(_t("Notiz liegt außerhalb der freigegebenen Ordner: {normalized} (erlaubt: {items})", normalized=normalized, items=', '.join(folders)))
    return normalized


def _strip_md(path: str) -> str:
    path = path.strip().replace("\\", "/")
    return path[:-3] if path.lower().endswith(".md") else path


def note_title(path: str, text: str) -> str:
    """Erste H1, gekürzt vor " · " bzw. vor einem Gedankenstrich; ohne H1 der letzte Pfadteil."""
    heading = first_heading(text)
    if not heading:
        return path.rsplit("/", 1)[-1]
    for separator in _TITLE_SEPARATORS:
        heading = heading.split(separator, 1)[0]
    return heading.strip() or path.rsplit("/", 1)[-1]


def note_values(path: str, text: str) -> dict[str, str]:
    """Label-Werte einer Notiz: Frontmatter, fette Schlüssel, abgeleitete Werte (erster gewinnt)."""
    meta, _body = split_frontmatter(text)
    values: dict[str, str] = {}
    for key, value in meta.items():
        norm = normalize_key(key)
        if norm and norm not in values:
            values[norm] = value
    for key, value in bold_bullets(text).items():
        values.setdefault(key, value)
    name = path.rsplit("/", 1)[-1]
    values.setdefault("name", name)
    values.setdefault("host", values["name"])
    values.setdefault("titel", note_title(path, text))
    values.setdefault("pfad", path)
    for key in ("ip", "ipv4"):
        if key in values:
            match = IPV4_RE.search(values[key])
            if match:
                values[key] = match.group(0)
    for key in ("vmid", "id"):
        if key in values:
            match = _NUMBER_RE.search(values[key])
            if match:
                values[key] = match.group(0)
    return values


def print_line(day: date, summary: str, png_name: str | None = None) -> str:
    """Vermerkzeile für die Notiz, z. B. `- 2026-09-26 Label gedruckt: pmx10 · SSD-1 ![[label.png]]`."""
    line = _t("- {isoformat} Label gedruckt: {summary}", isoformat=day.isoformat(), summary=summary)
    return f"{line} ![[{png_name}]]" if png_name else line


def attachment_dir(data: dict) -> Path | None:
    """Anhangsordner im lokalen Vault-Ordner (`vault_dir/attachments_dir`), sonst None."""
    section = data.get("obsidian", {})
    vault_dir = section.get("vault_dir")
    if not vault_dir:
        return None
    return Path(vault_dir) / str(section.get("attachments_dir") or "")


def _list_entries(result: Any) -> list[str]:
    if isinstance(result, str):
        stripped = result.strip()
        if stripped.startswith("["):
            try:
                return _list_entries(json.loads(stripped))
            except ValueError:
                pass
        entries = []
        for line in stripped.splitlines():
            line = line.strip()
            if line.startswith(("- ", "* ")):
                line = line[2:].strip()
            if line:
                entries.append(line)
        return entries
    if isinstance(result, dict):
        for key in ("notes", "files", "result", "paths"):
            if key in result:
                return _list_entries(result[key])
        return []
    if isinstance(result, (list, tuple)):
        entries = []
        for item in result:
            if isinstance(item, dict):
                item = item.get("path") or item.get("name") or ""
            if str(item).strip():
                entries.append(str(item).strip())
        return entries
    return []


def parse_search(result: Any) -> list[VaultHit]:
    """Treffer aus dem Ergebnis von `vault_search` (tolerant, Format nicht garantiert)."""
    if isinstance(result, list):
        hits = []
        for item in result:
            if isinstance(item, dict) and item.get("path"):
                line = item.get("line")
                hits.append(VaultHit(_strip_md(str(item["path"])),
                                     int(line) if isinstance(line, int) or str(line).isdigit() else None,
                                     str(item.get("text", ""))))
            elif isinstance(item, str):
                hits.extend(parse_search(item))
        return hits
    if not isinstance(result, str):
        return []
    hits: list[VaultHit] = []
    current: str | None = None
    for raw in result.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        if not line[0].isspace():
            match = _HIT_MD_RE.match(line) or _HIT_SLASH_RE.match(line)
            if match:
                current = _strip_md(match.group("path"))
                hits.append(VaultHit(current, int(match.group("line")), match.group("text").strip()))
                continue
            header = line.strip().rstrip(":")
            current = _strip_md(header) if header.lower().endswith(".md") else None
            continue
        grouped = _GROUPED_HIT_RE.match(line)
        if grouped and current:
            hits.append(VaultHit(current, int(grouped.group("line")), grouped.group("text").strip()))
    return hits


class VaultClient:
    """Zugriff auf den Vault über den MCP-Server mit Ordnerfreigabe."""

    def __init__(self, mcp_url: str, *, timeout_s: float = 10.0, transport=None,
                 folders: Sequence[str] | None = None, vault_dir: str | Path | None = None):
        self.folders: tuple[str, ...] | None = tuple(folders) if folders is not None else None
        self.vault_dir: Path | None = Path(vault_dir) if vault_dir else None
        self.used_local = False  # True, sobald ein Lesezugriff auf den lokalen Ordner ausgewichen ist
        self._mcp = McpClient(mcp_url, service=SERVICE, timeout_s=timeout_s, transport=transport)

    @classmethod
    def from_settings(cls, data: dict, *, transport=None) -> "VaultClient":
        section = data.get("obsidian", {})
        return cls(section.get("mcp_url"), timeout_s=float(section.get("timeout_s", 10.0)),
                   transport=transport, folders=allowed_folders(data), vault_dir=section.get("vault_dir"))

    def _check(self, path: str) -> str:
        return validate_note_path(path, self.folders)

    # ---------- lokaler Rückfall (nur Lesen) ----------

    def _local_root(self) -> Path | None:
        if self.vault_dir is None or not self.vault_dir.is_dir():
            return None
        return self.vault_dir.resolve()

    def _local_list(self, root: Path, folder: str) -> list[str]:
        base = (root / folder).resolve() if folder else root
        if not base.is_relative_to(root) or not base.is_dir():
            return []
        allowed = None if self.folders is None else {f.lower() for f in self.folders}
        notes = set()
        for file in base.rglob("*.md"):
            rel = file.relative_to(root).as_posix()[:-3]
            parts = rel.split("/")
            if any(part.startswith(".") for part in parts):
                continue
            if allowed is not None and parts[0].lower() not in allowed:
                continue
            notes.add(rel)
        return sorted(notes)

    def _local_read(self, root: Path, normalized: str, error: Exception) -> str:
        file = (root / f"{normalized}.md").resolve()
        if not file.is_relative_to(root) or not file.is_file():
            raise error
        return file.read_text(encoding="utf-8")

    # ---------- MCP ----------

    def list_notes(self, folder: str = "") -> list[str]:
        folder_arg = self._check(folder) if folder.strip() else ""
        try:
            result = self._mcp.call_tool("vault_list", {"folder": folder_arg})
        except (NotReachable, NotConfigured):
            root = self._local_root()
            if root is None:
                raise
            self.used_local = True
            return self._local_list(root, folder_arg)
        entries = [_strip_md(e) for e in _list_entries(result)]
        return sorted({e for e in entries if e and not e.endswith("/")})

    def read(self, path: str) -> str:
        normalized = self._check(path)
        try:
            result = self._mcp.call_tool("vault_read", {"path": normalized})
        except (NotReachable, NotConfigured) as exc:
            root = self._local_root()
            if root is None:
                raise
            self.used_local = True
            return self._local_read(root, normalized, exc)
        return result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)

    def note(self, path: str) -> Note:
        normalized = self._check(path)
        text = self.read(normalized)
        return Note(path=normalized, title=note_title(normalized, text), text=text,
                    values=note_values(normalized, text), tables=tuple(tables(text)))

    def search(self, query: str, *, max_results: int = 30) -> list[VaultHit]:
        result = self._mcp.call_tool("vault_search", {"query": query, "max_results": max_results,
                                                      "context_lines": 0})
        return parse_search(result)

    def append(self, path: str, content: str) -> None:
        self._mcp.call_tool("vault_append", {"path": self._check(path), "content": content})

    def write(self, path: str, content: str, *, overwrite: bool = False) -> None:
        self._mcp.call_tool("vault_write", {"path": self._check(path), "content": content,
                                            "overwrite": overwrite})

    def changelog(self, title: str, entry: str, *, day: date | None = None) -> None:
        self._mcp.call_tool("changelog_add", {"title": title, "entry": entry,
                                              "date": day.isoformat() if day else ""})

    def close(self) -> None:
        self._mcp.close()

    def __enter__(self) -> "VaultClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
