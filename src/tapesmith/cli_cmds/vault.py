"""Plugin-Befehl 'tapesmith vault': Obsidian-Vault als Datenquelle und Rückkanal.

Unterbefehle: `list [ORDNER]`, `show NOTIZ [--json]`, `print NOTIZ --template NAME` (Einzellabel aus
den Notizwerten, danach Vermerk in der Notiz, wenn `obsidian.append_after_print` an ist oder
`--vermerk`), `table NOTIZ NR` (Tabelle der Notiz als Serie) und `snippet` (PNG und Markdown-Zeile
aus dem Verlauf). Der MCP-Server wird nur über `VaultClient.from_settings` angesprochen; `TRANSPORT`
und `CLIP_BACKEND` ersetzen Tests.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from datetime import date
from pathlib import Path

from tapesmith import paths
from tapesmith.cli_cmds.base import CliContext, add_print_options, parse_sets
from tapesmith.errors import EXIT_ERROR, EXIT_OK
from tapesmith.history import HistoryStore
from tapesmith.integrations import cliprint, settings, snippet, winclip
from tapesmith.integrations.frontmatter import normalize_key
from tapesmith.integrations.obsidian import Note, VaultClient, allowed_folders, attachment_dir, validate_note_path
from tapesmith.templates.fill import input_fields
from tapesmith.templates.store import find_template
from tapesmith.i18n import N_, _t

COMMAND = "vault"
HELP = N_("Obsidian-Vault: Notizen lesen, Labels daraus drucken, Vermerk und Snippet")

# Für Tests: httpx-Transport des MCP-Clients und Backend der Zwischenablage.
TRANSPORT = None
CLIP_BACKEND: Callable[[str], None] | None = None


def register(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="vault_cmd", required=True)

    p_list = sub.add_parser("list", help=_t("Notizen der freigegebenen Ordner auflisten"))
    p_list.add_argument("folder", nargs="?", default="", metavar=_t("ORDNER"), help=_t("nur dieser Ordner"))

    p_show = sub.add_parser("show", help=_t("Werte und Tabellen einer Notiz zeigen"))
    p_show.add_argument("note", metavar=_t("NOTIZ"), help=_t("z. B. Hosts/pmx10"))
    p_show.add_argument("--json", action="store_true", help=_t("Ausgabe als JSON"))

    p_print = sub.add_parser("print", help=_t("Label aus den Werten einer Notiz drucken"))
    p_print.add_argument("note", metavar=_t("NOTIZ"))
    p_print.add_argument("--template", required=True, metavar=_t("NAME|PFAD"), help=_t("Vorlage"))
    p_print.add_argument("--set", action="append", default=[], metavar=_t("FELD=SCHLÜSSEL"),
                         help=_t("Feld der Vorlage aus diesem Notizschlüssel füllen, z. B. host=name"))
    mark = p_print.add_mutually_exclusive_group()
    mark.add_argument("--vermerk", action="store_true",
                      help=_t("nach dem Druck immer einen Vermerk an die Notiz anhängen"))
    mark.add_argument("--kein-vermerk", action="store_true",
                      help=_t("keinen Vermerk anhängen (auch wenn obsidian.append_after_print an ist)"))
    add_print_options(p_print)

    p_table = sub.add_parser("table", help=_t("Tabelle einer Notiz als Serie drucken"))
    p_table.add_argument("note", metavar=_t("NOTIZ"))
    p_table.add_argument("number", type=int, metavar=_t("NR"), help=_t("Nummer der Tabelle (ab 1, siehe show)"))
    p_table.add_argument("--spalte", action="append", default=[], metavar=_t("SPALTE=FELD"),
                         help=_t('Spalte der Tabelle einem Feld zuordnen, z. B. "Seriennummer=sn"'))
    cliprint.add_series_options(p_table, template="datentraeger")

    p_snip = sub.add_parser("snippet", help=_t("PNG und Markdown-Zeile für die Vault-Notiz aus dem Verlauf"))
    p_snip.add_argument("--id", type=int, metavar="N", help=_t("Verlaufseintrag (Standard: der letzte)"))
    p_snip.add_argument("--anhang", action="store_true", help=_t("PNG im Anhangsordner des Vaults ablegen"))
    p_snip.add_argument("--an", metavar=_t("NOTIZ"), help=_t("Markdown-Zeile an diese Notiz anhängen"))
    p_snip.add_argument("--kopieren", action="store_true", help=_t("Markdown-Zeile in die Zwischenablage"))
    p_snip.add_argument("--png", type=Path, metavar=_t("DATEI"), help=_t("PNG zusätzlich hierhin schreiben"))


def _client(data: dict) -> VaultClient:
    return VaultClient.from_settings(data, transport=TRANSPORT)


def _list(args: argparse.Namespace, ctx: CliContext, data: dict) -> int:
    with _client(data) as vault:
        if args.folder.strip():
            notes = vault.list_notes(args.folder)
        else:
            notes = []
            for folder in data["obsidian"]["folders"]:
                notes.extend(n for n in vault.list_notes(folder) if n not in notes)
    if not notes:
        ctx.out(_t("Keine Notizen gefunden"))
    for note in notes:
        ctx.out(note)
    return EXIT_OK


def _note_json(note: Note) -> dict:
    return {"path": note.path, "title": note.title, "values": note.values,
            "tables": [{"heading": t.heading, "headers": list(t.headers), "rows": [list(r) for r in t.rows]}
                       for t in note.tables]}


def _show(args: argparse.Namespace, ctx: CliContext, data: dict) -> int:
    with _client(data) as vault:
        note = vault.note(args.note)
    if args.json:
        ctx.out(json.dumps(_note_json(note), ensure_ascii=False, indent=2))
        return EXIT_OK
    ctx.out(f"{note.title} ({note.path})")
    width = max((len(k) for k in note.values), default=8)
    ctx.out(f"{'Schlüssel':<{width}}  Wert")
    for key, value in note.values.items():
        ctx.out(f"{key:<{width}}  {value}")
    for number, table in enumerate(note.tables, start=1):
        heading = f" ({table.heading})" if table.heading else ""
        ctx.out(_t("Tabelle {number}{heading}: {items} [{count} Zeilen]", number=number, heading=heading, items=' | '.join(table.headers), count=len(table.rows)))
    return EXIT_OK


def _mapped_values(note: Note, sets: list[str]) -> dict[str, str]:
    values = dict(note.values)
    for field, source in parse_sets(sets).items():
        source = source.strip()
        if source not in note.values:
            raise ValueError(_t("Notiz {path} hat keinen Wert '{source}' (vorhanden: {items})", path=note.path, source=source, items=', '.join(note.values)))
        values[field] = note.values[source]
    return values


def _print(args: argparse.Namespace, ctx: CliContext, data: dict) -> int:
    with _client(data) as vault:
        note = vault.note(args.note)
        values = _mapped_values(note, args.set)

        def after_print() -> None:
            # gedruckte Werte in Feldreihenfolge der Vorlage (wie im Verlauf)
            printed = {f.id: values[f.id] for f in input_fields(find_template(args.template)) if f.id in values}
            summary = snippet.summary_from_values(printed, note.path)
            result = snippet.append_after_print(vault, data, note.path, summary, day=date.today(),
                                                force=args.vermerk)
            if result.appended:
                ctx.out(_t("Vermerk angehängt: {line}", line=result.line))

        callback = None if args.kein_vermerk else after_print
        return cliprint.print_one(ctx, args, args.template, values, on_printed=callback)


def _table_rows(note: Note, number: int, spalten: list[str]) -> list[dict[str, str]]:
    if not 1 <= number <= len(note.tables):
        raise ValueError(_t("Die Notiz {path} hat keine Tabelle {number} (vorhanden: {count})", path=note.path, number=number, count=len(note.tables)))
    table = note.tables[number - 1]
    if spalten:
        mapping = parse_sets(spalten)
        for column in mapping:
            if column not in table.headers:
                raise ValueError(_t("Spalte '{column}' fehlt in der Tabelle (vorhanden: {items})", column=column, items=', '.join(table.headers)))
        columns = [(table.headers.index(column), field.strip()) for column, field in mapping.items()]
    else:
        columns = [(i, normalize_key(h)) for i, h in enumerate(table.headers)]
    rows = []
    for row in table.rows:
        values = {"host": note.values.get("host", "")}
        values.update({field: row[index] for index, field in columns if field})
        rows.append(values)
    return rows


def _table(args: argparse.Namespace, ctx: CliContext, data: dict) -> int:
    with _client(data) as vault:
        note = vault.note(args.note)
    rows = _table_rows(note, args.number, args.spalte)
    return cliprint.print_rows(ctx, args, args.template, rows)


def _snippet(args: argparse.Namespace, ctx: CliContext, data: dict) -> int:
    profile = ctx.load_profile()
    with HistoryStore(paths.history_db_path()) as store:
        snip = snippet.snippet_for(store, profile, args.id)
    if args.an:
        # Pfad vor dem Ablegen prüfen, damit bei gesperrtem Ordner nichts geschrieben wird
        validate_note_path(args.an, allowed_folders(data))
    if args.anhang:
        target = attachment_dir(data)
        if target is None:
            ctx.err(_t("Hinweis: obsidian.vault_dir ist nicht gesetzt, PNG mit --png speichern und selbst ablegen"))
        else:
            snip, saved = snippet.store_attachment(snip, target)
            ctx.out(_t("Abgelegt: {saved}", saved=saved))
    if args.png:
        args.png.parent.mkdir(parents=True, exist_ok=True)
        args.png.write_bytes(snip.png)
        ctx.out(f"PNG: {args.png}")
    if args.an:
        with _client(data) as vault:
            vault.append(args.an, "\n" + snip.markdown)
        ctx.out(_t("Angehängt an {an}", an=args.an))
    ctx.out(snip.markdown)
    if args.kopieren:
        try:
            winclip.copy_text(snip.markdown, backend=CLIP_BACKEND)
        except RuntimeError as exc:
            ctx.err(str(exc))
            return EXIT_ERROR
        ctx.out(_t("In die Zwischenablage kopiert"))
    return EXIT_OK


def _dispatch(args: argparse.Namespace, ctx: CliContext) -> int:
    data = settings.load_settings()
    handlers = {"list": _list, "show": _show, "print": _print, "table": _table, "snippet": _snippet}
    handler = handlers.get(args.vault_cmd)
    if handler is None:
        raise ValueError(_t("Unbekannter Unterbefehl 'vault {vault_cmd}'", vault_cmd=args.vault_cmd))
    return handler(args, ctx, data)


def run(args: argparse.Namespace, ctx: CliContext) -> int:
    return cliprint.run_guarded(ctx, lambda: _dispatch(args, ctx))
