"""Vault-Snippet aus dem Verlauf und Vermerk nach dem Druck.

Aus einem Verlaufseintrag entstehen ein 1-Bit-PNG und eine Markdown-Zeile zum Einfügen in eine
Notiz (`- 2026-09-26 Label gedruckt: pmx10 · SSD-1 · SN 274913 ![[label-….png]]`). Nach einem
erfolgreichen Druck hängt `append_after_print` diese Zeile an die Quell-Notiz an, wenn
`obsidian.append_after_print` eingeschaltet ist oder der Nutzer es ausdrücklich verlangt.
"""

from __future__ import annotations

import dataclasses
import io
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from PIL import Image

from tapesmith.device.profile import DeviceProfile
from tapesmith.export import export_heads
from tapesmith.fileutil import atomic_write_bytes
from tapesmith.history import HistoryEntry, HistoryStore
from tapesmith.integrations.obsidian import VaultClient, attachment_dir, print_line, validate_note_path
from tapesmith.i18n import N_, _t

SERIAL_KEYS = frozenset({"sn", "seriennummer"})
SERIAL_TAIL = 6
NO_ENTRY_MESSAGE = N_("Kein gedrucktes Label mit Bild im Verlauf")


@dataclass(frozen=True)
class Snippet:
    history_id: int
    file_name: str
    png: bytes
    markdown: str
    changelog_md: str
    summary: str


@dataclass(frozen=True)
class AfterPrint:
    appended: bool
    line: str | None
    saved_path: str | None
    reason: str


def summary_from_values(values: Mapping[str, str], fallback: str) -> str:
    """Werte in Reihenfolge, leere weg, Seriennummern als `SN <letzte 6>`, mit ` · ` verbunden."""
    parts: list[str] = []
    for key, value in values.items():
        text = str(value or "").strip()
        if not text:
            continue
        if key.lower() in SERIAL_KEYS:
            text = f"SN {text[-SERIAL_TAIL:]}"
        parts.append(text)
    return " · ".join(parts) if parts else fallback


def summary_for(entry: HistoryEntry) -> str:
    return summary_from_values(entry.values, entry.title)


def _png_1bit(head: Image.Image, profile: DeviceProfile) -> bytes:
    with tempfile.TemporaryDirectory(prefix="p12-snippet-") as tmp:
        path = export_heads(Path(tmp) / "label.png", [head], profile, fmt="png")
        with Image.open(path) as image:
            mono = image.convert("1")
    buf = io.BytesIO()
    mono.save(buf, format="PNG")
    return buf.getvalue()


def build_snippet(entry: HistoryEntry, head: Image.Image, profile: DeviceProfile, *,
                  day: date | None = None) -> Snippet:
    """PNG (1 Bit) und Markdown-Zeile für einen Verlaufseintrag."""
    file_name = f"label-{entry.created:%Y%m%d-%H%M%S}-{entry.id}.png"
    summary = summary_for(entry)
    markdown = print_line(day or entry.created.date(), summary, file_name)
    return Snippet(history_id=entry.id, file_name=file_name, png=_png_1bit(head, profile),
                   markdown=markdown, changelog_md=_t("- Label gedruckt: {summary} (Verlauf #{id})", summary=summary, id=entry.id),
                   summary=summary)


def save_attachment(snippet: Snippet, target_dir: Path) -> Path:
    """Schreibt das PNG atomar in `target_dir`; vorhandene Dateien bleiben (Suffix -2, -3 …)."""
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    base = Path(snippet.file_name)
    path = target_dir / base.name
    counter = 2
    while path.exists():
        path = target_dir / f"{base.stem}-{counter}{base.suffix}"
        counter += 1
    atomic_write_bytes(path, snippet.png)
    return path


def store_attachment(snippet: Snippet, target_dir: Path) -> tuple[Snippet, Path]:
    """`save_attachment` und Snippet mit dem tatsächlichen Dateinamen (Einbettung angepasst)."""
    saved = save_attachment(snippet, target_dir)
    if saved.name == snippet.file_name:
        return snippet, saved
    markdown = snippet.markdown.replace(f"![[{snippet.file_name}]]", f"![[{saved.name}]]")
    return dataclasses.replace(snippet, file_name=saved.name, markdown=markdown), saved


def snippet_for(history: HistoryStore, profile: DeviceProfile, history_id: int | None) -> Snippet:
    """Snippet für einen Eintrag (None: der letzte); ohne Eintrag oder Bild ValueError."""
    if history_id is None:
        entry = history.last()
        if entry is None:
            raise ValueError(_t(NO_ENTRY_MESSAGE))
    else:
        entry = history.get(history_id)
    head = history.head_image(entry.id)
    if head is None:
        raise ValueError(_t(NO_ENTRY_MESSAGE))
    return build_snippet(entry, head, profile)


def append_after_print(vault: VaultClient, data: dict, note_path: str, summary: str, *, day: date,
                       force: bool = False, snippet: Snippet | None = None) -> AfterPrint:
    """Rückkanal nach einem erfolgreichen Druck: Vermerk an die Quell-Notiz anhängen."""
    # Pfad immer zuerst prüfen (ohne MCP-Aufruf), damit bei gesperrtem Ordner keine verwaiste Datei entsteht
    note_path = validate_note_path(note_path, vault.folders)
    enabled = bool(data.get("obsidian", {}).get("append_after_print", False))
    if not (enabled or force):
        return AfterPrint(False, None, None, "ausgeschaltet")
    png_name: str | None = None
    saved_path: str | None = None
    target = attachment_dir(data)
    if snippet is not None and target is not None:
        saved = save_attachment(snippet, target)
        png_name = saved.name
        saved_path = str(saved)
    line = print_line(day, summary, png_name)
    vault.append(note_path, "\n" + line)
    return AfterPrint(True, line, saved_path, "")
