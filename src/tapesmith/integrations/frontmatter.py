"""Frontmatter- und Markdown-Parser für Vault-Notizen, ohne PyYAML.

Liest das einfache YAML-Frontmatter von Obsidian (Schlüssel: Wert, Listen in Klammern oder als
Folgezeilen), fette Aufzählungsschlüssel (`- **IP:** 192.0.2.99`) und GitHub-Tabellen. Die
Host-Notizen des Vaults haben meist kein Frontmatter; die Daten stehen in fetten Schlüsseln und
Tabellen.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss",
                          "Ä": "ae", "Ö": "oe", "Ü": "ue"})
_KEY_RE = re.compile(r"^([A-Za-z0-9_][^:]*?)\s*:(?:\s+(.*)|\s*)$")
_LIST_ITEM_RE = re.compile(r"^\s+-\s+(.*)$")
_BOLD_BULLET_RE = re.compile(r"^[-*+]\s+\*\*(.+?)(?::\*\*|\*\*\s*:)\s*(.*)$")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_SEPARATOR_CELL_RE = re.compile(r"^:?-{3,}:?$|^:?-+:?$")


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _inline_list(value: str) -> str:
    inner = value.strip()[1:-1]
    return ", ".join(_unquote(part) for part in inner.split(",") if part.strip())


def split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """(Frontmatter als flaches dict, Rest). Kein bzw. nicht geschlossenes Frontmatter: ({}, text)."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        return {}, text
    end = None
    for index in range(1, len(lines)):
        if lines[index].rstrip("\r\n").rstrip() in ("---", "..."):
            end = index
            break
    if end is None:
        return {}, text
    meta: dict[str, str] = {}
    current: str | None = None
    items: list[str] = []
    nested = False

    def finish() -> None:
        if current is not None and items:
            meta[current] = ", ".join(items)

    for raw in lines[1:end]:
        line = raw.rstrip("\r\n")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[0] in " \t":
            if current is None or nested:
                continue
            match = _LIST_ITEM_RE.match(line)
            if match:
                items.append(_unquote(match.group(1)))
            else:
                # verschachteltes Objekt: ganzen Schlüssel verwerfen
                meta.pop(current, None)
                nested = True
                items.clear()
            continue
        finish()
        items = []
        nested = False
        current = None
        match = _KEY_RE.match(line)
        if not match:
            continue
        key = match.group(1).strip()
        value = (match.group(2) or "").strip()
        current = key
        if value.startswith("[") and value.endswith("]"):
            meta[key] = _inline_list(value)
        elif value.startswith("{"):
            nested = True
        else:
            meta[key] = _unquote(value)
    finish()
    body = "".join(lines[end + 1:])
    return meta, body


def normalize_key(label: str) -> str:
    """Schlüssel für Werte: klein, Umlaute umschrieben, sonst nur a-z0-9 und `_`."""
    text = label.strip().translate(_UMLAUTS).lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def strip_markdown(text: str) -> str:
    """Entfernt Code-, Fett-, Kursiv- und Link-Auszeichnungen (Emojis bleiben)."""
    out = text.replace("\\|", "|")
    out = re.sub(r"!?\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2", out)
    out = re.sub(r"!?\[\[([^\]]+)\]\]", lambda m: m.group(1).split("#")[0].rsplit("/", 1)[-1], out)
    out = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", out)
    out = re.sub(r"`([^`]*)`", r"\1", out)
    out = re.sub(r"(\*\*|__)(.+?)\1", r"\2", out)
    out = re.sub(r"(?<![\w*])\*(?!\s)([^*]+?)\*(?![\w*])", r"\1", out)
    out = re.sub(r"(?<![\w_])_(?!\s)([^_]+?)_(?![\w_])", r"\1", out)
    return out.strip()


def bold_bullets(text: str) -> dict[str, str]:
    """Aufzählungen der ersten Ebene `- **Schlüssel:** Wert` als {normalize_key: Wert ohne Markdown}."""
    values: dict[str, str] = {}
    for line in text.splitlines():
        match = _BOLD_BULLET_RE.match(line.rstrip())
        if not match:
            continue
        key = normalize_key(strip_markdown(match.group(1)))
        if key and key not in values:
            values[key] = strip_markdown(match.group(2))
    return values


@dataclass(frozen=True)
class MdTable:
    heading: str | None
    headers: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]


def _cells(line: str) -> list[str]:
    inner = line.strip()
    if inner.startswith("|"):
        inner = inner[1:]
    if inner.endswith("|") and not inner.endswith("\\|"):
        inner = inner[:-1]
    return [c.strip() for c in re.split(r"(?<!\\)\|", inner)]


def _is_table_line(line: str) -> bool:
    return line.strip().startswith("|")


def _is_separator(line: str) -> bool:
    cells = _cells(line)
    return bool(cells) and all(_SEPARATOR_CELL_RE.match(c.replace(" ", "")) for c in cells)


def tables(text: str) -> list[MdTable]:
    """Alle GitHub-Tabellen (Kopfzeile, Trennzeile `|---|`, Zeilen) mit der nächsten Überschrift darüber."""
    _meta, body = split_frontmatter(text)
    lines = body.splitlines()
    found: list[MdTable] = []
    heading: str | None = None
    index = 0
    while index < len(lines):
        line = lines[index]
        match = _HEADING_RE.match(line)
        if match:
            heading = strip_markdown(match.group(2))
            index += 1
            continue
        if (_is_table_line(line) and index + 1 < len(lines) and _is_table_line(lines[index + 1])
                and _is_separator(lines[index + 1])):
            headers = tuple(strip_markdown(c) for c in _cells(line))
            width = len(headers)
            rows: list[tuple[str, ...]] = []
            index += 2
            while index < len(lines) and _is_table_line(lines[index]):
                cells = [strip_markdown(c) for c in _cells(lines[index])][:width]
                cells += [""] * (width - len(cells))
                rows.append(tuple(cells))
                index += 1
            found.append(MdTable(heading, headers, tuple(rows)))
            continue
        index += 1
    return found


def first_heading(text: str) -> str | None:
    """Text der ersten H1-Überschrift (nach dem Frontmatter), sonst None."""
    _meta, body = split_frontmatter(text)
    for line in body.splitlines():
        match = _HEADING_RE.match(line)
        if match and len(match.group(1)) == 1:
            return match.group(2).strip()
    return None
