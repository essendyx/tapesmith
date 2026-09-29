"""Vault-Notiz aus einem Asset.

Aus einem Asset entsteht auf Knopfdruck eine Notiz `Assets/<ID>` über den MCP, nie überschreibend.
Die Ordnerfreigabe prüft der `VaultClient` selbst (Ordner `Assets` ist über `obsidian.ALWAYS_ALLOWED`
immer freigegeben); `create_note` ruft `validate_note_path` nicht zusätzlich auf.
"""

from __future__ import annotations

import re
from datetime import date

from tapesmith.integrations import shortlink
from tapesmith.integrations.assets import Asset
from tapesmith.integrations.errors import IntegrationError
from tapesmith.integrations.obsidian import VaultClient
from tapesmith.i18n import _t

_EXISTS_HINTS = ("existier", "already exists")
_DOC_ID_RE = re.compile(r"/documents/(\d+)/")


def note_path(asset_id: str) -> str:
    """Notizpfad eines Assets, z. B. `"Assets/HL-0042"`."""
    return f"Assets/{asset_id}"


def paperless_document_url(data: dict, doc_id: int) -> str:
    """Link zum Paperless-Dokument (`public_url` bevorzugt, sonst `url`)."""
    section = data.get("paperless", {})
    base = section.get("public_url") or section.get("url") or ""
    return f"{base.rstrip('/')}/documents/{doc_id}/details"


def note_markdown(asset: Asset, *, short_link: str | None, paperless_url: str | None, today: date) -> str:
    """Markdown der Asset-Notiz; leere Zeilen (Kurz-Link, Rechnung, Host, SN) werden weggelassen."""
    lines = [f"# {asset.id} · {asset.bezeichnung}", "",
             f"- **Asset:** {asset.id}",
             _t("- **Bezeichnung:** {bezeichnung}", bezeichnung=asset.bezeichnung),
             _t("- **Kategorie:** {kategorie}", kategorie=asset.kategorie),
             _t("- **Standort:** {standort}", standort=asset.standort)]
    if asset.seriennummer:
        lines.append(_t("- **Seriennummer:** {seriennummer}", seriennummer=asset.seriennummer))
    if asset.host:
        lines.append(f"- **Host:** [[Hosts/{asset.host}]]")
    if short_link:
        lines.append(_t("- **Kurz-Link:** {short_link}", short_link=short_link))
    if paperless_url:
        match = _DOC_ID_RE.search(paperless_url)
        label = _t("Paperless-Dokument {group}", group=match.group(1)) if match else _t("Paperless-Dokument")
        lines.append(_t("- **Rechnung:** [{label}]({paperless_url})", label=label, paperless_url=paperless_url))
    lines.append(f"- **Status:** {asset.status}")
    lines.append(_t("- **Angelegt:** {isoformat} (tapesmith)", isoformat=today.isoformat()))
    return "\n".join(lines) + "\n"


class NoteExists(ValueError):
    """Die Notiz gibt es schon (nie überschrieben)."""


def create_note(vault: VaultClient, data: dict, asset: Asset, *, today: date) -> str:
    """Legt `Assets/<ID>` an (nie überschreibend) und gibt den Pfad zurück.

    `vault` kommt immer aus `VaultClient.from_settings(data, transport=...)`; die
    Ordnerprüfung sitzt im Client. Existiert die Notiz schon, meldet der MCP einen Fehler: daraus
    wird `NoteExists("Notiz Assets/HL-0042 existiert bereits")` (ein `ValueError`)."""
    short_link = shortlink.short_url(data["shortlink"]["base_url"], asset.id) if shortlink.configured(data) else None
    paperless_url = paperless_document_url(data, asset.paperless_doc) if asset.paperless_doc else None
    markdown = note_markdown(asset, short_link=short_link, paperless_url=paperless_url, today=today)
    path = note_path(asset.id)
    try:
        vault.write(path, markdown, overwrite=False)
    except IntegrationError as exc:
        text = str(exc).casefold()
        if any(hint in text for hint in _EXISTS_HINTS):
            raise NoteExists(_t("Notiz {path} existiert bereits", path=path)) from exc
        raise
    return path
