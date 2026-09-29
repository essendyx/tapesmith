"""Routen /api/v1/homelab/vault (Obsidian-Vault).

Notizen listen und lesen, eine Notiz-Tabelle als Serie vorbereiten, Vault-Snippet aus dem Verlauf
bauen, Vermerk nach einem erfolgreichen Druck anhängen (`/printed`, wertet
`obsidian.append_after_print` aus) und Changelog-Einträge anlegen. Die Ordnerfreigabe prüft der
`VaultClient` (ValueError ergibt 422). Registriert wird der Router über `webapi.homelab_routers`.
"""

from __future__ import annotations

import base64

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from tapesmith.integrations import snippet as snippet_mod
from tapesmith.integrations.frontmatter import MdTable, normalize_key
from tapesmith.integrations.obsidian import VaultClient, attachment_dir, validate_note_path
from tapesmith.webapi.context import ApiContext, get_ctx
from tapesmith.webapi.errors import NotFound
from tapesmith.webapi.homelab_common import load_homelab, pending_table, transport_for
from tapesmith.i18n import N_, _t

router = APIRouter()

MAX_LINE = 500
NO_VAULT_DIR_WARNING = N_("obsidian.vault_dir ist nicht gesetzt, PNG bitte herunterladen und selbst ablegen")


class TableBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    path: str
    table: int = Field(ge=0)
    columns: dict[str, str] | None = None
    template: str | None = None


class SnippetBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    history_id: int | None = None
    save_attachment: StrictBool = False
    append_to: str | None = None


class AppendBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    path: str
    line: str = Field(min_length=1, max_length=MAX_LINE)


class PrintedBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    path: str
    history_id: int | None = None
    summary: str | None = Field(default=None, max_length=MAX_LINE)
    force: StrictBool = False


class ChangelogBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    title: str = Field(min_length=1, max_length=120)
    entry: str = Field(min_length=1, max_length=4000)


def _vault(ctx: ApiContext, data: dict) -> VaultClient:
    return VaultClient.from_settings(data, transport=transport_for(ctx, "obsidian"))


def _table_json(table: MdTable) -> dict:
    return {"heading": table.heading, "headers": list(table.headers), "rows": [list(r) for r in table.rows]}


def _snippet(ctx: ApiContext, history_id: int | None) -> snippet_mod.Snippet:
    try:
        return snippet_mod.snippet_for(ctx.history(), ctx.profile(), history_id)
    except KeyError as exc:
        raise NotFound(str(exc.args[0]) if exc.args else _t("Verlaufseintrag fehlt")) from exc


def _single_line(text: str) -> str:
    if "\n" in text or "\r" in text:
        raise ValueError(_t("Die Zeile darf keine Zeilenumbrüche enthalten"))
    return text.strip()


@router.get("/homelab/vault/notes")
def vault_notes(folder: str = "", ctx: ApiContext = Depends(get_ctx)) -> dict:
    data = load_homelab(ctx)
    folders = list(data["obsidian"]["folders"])
    with _vault(ctx, data) as vault:
        if folder.strip():
            notes = vault.list_notes(folder)
        else:
            notes = []
            for name in folders:
                notes.extend(n for n in vault.list_notes(name) if n not in notes)
    return {"folders": folders, "notes": notes}


@router.get("/homelab/vault/note")
def vault_note(path: str, ctx: ApiContext = Depends(get_ctx)) -> dict:
    data = load_homelab(ctx)
    with _vault(ctx, data) as vault:
        note = vault.note(path)
    return {"path": note.path, "title": note.title, "values": note.values,
            "tables": [_table_json(t) for t in note.tables]}


@router.post("/homelab/vault/table")
def vault_table(body: TableBody, ctx: ApiContext = Depends(get_ctx)) -> dict:
    data = load_homelab(ctx)
    with _vault(ctx, data) as vault:
        note = vault.note(body.path)
    if body.table >= len(note.tables):
        raise ValueError(_t("Die Notiz {path} hat keine Tabelle {value} (vorhanden: {count})", path=note.path, value=body.table + 1, count=len(note.tables)))
    table = note.tables[body.table]
    if body.columns:
        indexes = []
        for column in body.columns:
            if column not in table.headers:
                raise ValueError(_t("Spalte '{column}' fehlt in der Tabelle (vorhanden: {items})", column=column, items=', '.join(table.headers)))
            indexes.append(table.headers.index(column))
        headers = [str(v).strip() or normalize_key(k) for k, v in body.columns.items()]
        rows = [[row[i] for i in indexes] for row in table.rows]
    else:
        headers = [normalize_key(h) or f"spalte_{i + 1}" for i, h in enumerate(table.headers)]
        rows = [list(row) for row in table.rows]
    source = f"Vault {note.path}" + (f" · {table.heading}" if table.heading else "")
    pending_id = pending_table(ctx, headers, rows, source)
    return {"pending_id": pending_id, "count": len(rows), "headers": headers}


@router.post("/homelab/vault/snippet")
def vault_snippet(body: SnippetBody, ctx: ApiContext = Depends(get_ctx)) -> dict:
    data = load_homelab(ctx)
    snip = _snippet(ctx, body.history_id)
    warnings: list[str] = []
    saved_path: str | None = None
    appended = False
    vault = _vault(ctx, data) if body.append_to is not None else None
    try:
        append_to = validate_note_path(body.append_to, vault.folders) if vault is not None else None
        if body.save_attachment:
            target = attachment_dir(data)
            if target is None:
                warnings.append(_t(NO_VAULT_DIR_WARNING))
            else:
                snip, saved = snippet_mod.store_attachment(snip, target)
                saved_path = str(saved)
        if vault is not None and append_to is not None:
            vault.append(append_to, "\n" + snip.markdown)
            appended = True
    finally:
        if vault is not None:
            vault.close()
    return {"history_id": snip.history_id, "file_name": snip.file_name,
            "png": base64.b64encode(snip.png).decode("ascii"), "markdown": snip.markdown,
            "changelog_md": snip.changelog_md, "summary": snip.summary, "saved_path": saved_path,
            "appended": appended, "warnings": warnings}


@router.post("/homelab/vault/append")
def vault_append(body: AppendBody, ctx: ApiContext = Depends(get_ctx)) -> dict:
    line = _single_line(body.line)
    if not line:
        raise ValueError(_t("Die Zeile ist leer"))
    data = load_homelab(ctx)
    with _vault(ctx, data) as vault:
        vault.append(body.path, "\n" + line)
    return {"ok": True}


@router.post("/homelab/vault/printed")
def vault_printed(body: PrintedBody, ctx: ApiContext = Depends(get_ctx)) -> dict:
    data = load_homelab(ctx)
    summary = _single_line(body.summary) if body.summary else None
    snip = None
    if body.history_id is not None:
        store = ctx.history()
        try:
            entry = store.get(body.history_id)
        except KeyError as exc:
            raise NotFound(str(exc.args[0])) from exc
        if summary is None:
            summary = snippet_mod.summary_for(entry)
        if attachment_dir(data) is not None and store.head_image(entry.id) is not None:
            snip = snippet_mod.snippet_for(store, ctx.profile(), entry.id)
    if not summary:
        raise ValueError(_t("summary oder history_id nötig"))
    with _vault(ctx, data) as vault:
        result = snippet_mod.append_after_print(vault, data, body.path, summary, day=ctx.now().date(),
                                                force=body.force, snippet=snip)
    return {"appended": result.appended, "line": result.line, "saved_path": result.saved_path,
            "reason": result.reason}


@router.post("/homelab/vault/changelog")
def vault_changelog(body: ChangelogBody, ctx: ApiContext = Depends(get_ctx)) -> dict:
    data = load_homelab(ctx)
    with _vault(ctx, data) as vault:
        vault.changelog(body.title.strip(), body.entry)
    return {"ok": True}
