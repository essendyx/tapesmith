"""`tapesmith history`: Druckverlauf anzeigen, durchsuchen und einzelne Einträge einsehen."""

import argparse
import json

from tapesmith import paths
from tapesmith.cli_cmds.base import CliContext, positive_int
from tapesmith.history import HistoryStore
from tapesmith.i18n import N_, _t

COMMAND = "history"
HELP = N_("Druckverlauf anzeigen und durchsuchen")


def register(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("query", nargs="*", help=_t("Suchwörter (leer = neueste Einträge)"))
    parser.add_argument("--limit", type=positive_int, default=20, help=_t("maximale Anzahl Einträge"))
    parser.add_argument("--json", action="store_true", help=_t("Ausgabe als JSON"))
    parser.add_argument("--show", type=int, metavar="ID", help=_t("einzelnen Eintrag anzeigen"))
    parser.add_argument("--thumbnail", type=str, metavar=_t("PFAD"),
                         help=_t("mit --show: Miniatur als PNG dorthin schreiben"))


def _format_row(entry) -> str:
    line = (f"{entry.id:>5}  {entry.created:%d.%m.%Y %H:%M}  {entry.status:<13} "
            f"{entry.source:<8} {entry.length_mm:>5.0f} mm  {entry.title}")
    if entry.copies > 1:
        line += f"  ×{entry.copies}"
    if entry.chained:
        line += _t("  [Kette]")
    return line


def run(args: argparse.Namespace, ctx: CliContext) -> int:
    with HistoryStore(paths.history_db_path()) as store:
        if args.show is not None:
            try:
                entry = store.get(args.show)
            except KeyError as exc:
                raise ValueError(_t("Verlaufseintrag {show} gibt es nicht", show=args.show)) from exc
            if args.thumbnail:
                thumb = store.thumbnail(entry.id)
                if thumb is not None:
                    thumb.save(args.thumbnail)
            if args.json:
                ctx.out(json.dumps(entry.to_dict(), ensure_ascii=False, indent=2))
            else:
                data = entry.to_dict()
                for key, value in data.items():
                    ctx.out(f"{key}: {value}")
            return 0

        query = " ".join(args.query)
        entries = store.search(query, limit=args.limit)
        if args.json:
            ctx.out(json.dumps([e.to_dict() for e in entries], ensure_ascii=False, indent=2))
            return 0
        if not entries:
            if query:
                ctx.out(_t("Keine Treffer für '{query}'", query=query))
            else:
                ctx.out(_t("Verlauf ist leer"))
            return 0
        for entry in entries:
            ctx.out(_format_row(entry))
        return 0
