"""`tapesmith stats`: Bandverbrauch pro Monat, Vorlage, Quelle, Art oder Rolle."""

import argparse
import dataclasses
import json
from datetime import datetime

from tapesmith import paths, stats
from tapesmith.cli_cmds.base import CliContext
from tapesmith.history import HistoryStore
from tapesmith.tape.rolls import RollStore
from tapesmith.i18n import N_, _t

COMMAND = "stats"
HELP = N_("Bandverbrauch-Statistik anzeigen")

BY_CHOICES = (*stats.GROUPS, "rolle")


def register(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--by", choices=BY_CHOICES, default="monat", help=_t("Gruppierung"))
    parser.add_argument("--since", metavar=_t("JJJJ-MM"), help=_t("nur Einträge ab diesem Monat"))
    parser.add_argument("--json", action="store_true", help=_t("Ausgabe als JSON"))


def _parse_since(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m")
    except ValueError as exc:
        raise ValueError(_t("Ungültiger Monat '{text}' (Format JJJJ-MM)", text=text)) from exc


def _roll_table(ctx: CliContext, rows: list[stats.RollUsage]) -> None:
    if not rows:
        ctx.out(_t("Keine Rollen erfasst"))
        return
    ctx.out(f"{'Band':<24} {'Start':<19} {'Verbraucht/Länge':<20} {'Aufträge':>8}  beendet")
    for r in rows:
        verbrauch = f"{stats.format_m(r.used_mm)}/{stats.format_m(r.length_mm * r.factor)}"
        ctx.out(f"{r.tape_name:<24} {r.started[:19]:<19} {verbrauch:<20} {r.jobs:>8}  "
                f"{'ja' if r.finished else 'nein'}")


def _usage_table(ctx: CliContext, rows: list[stats.UsageRow], total: stats.UsageRow) -> None:
    ctx.out(f"{'Schlüssel':<24} {'Aufträge':>8} {'Labels':>8} {'Band':>12}")
    for r in rows:
        ctx.out(f"{r.key:<24} {r.jobs:>8} {r.labels:>8} {stats.format_m(r.tape_mm):>12}")
    ctx.out(f"{'Summe':<24} {total.jobs:>8} {total.labels:>8} {stats.format_m(total.tape_mm):>12}")


def run(args: argparse.Namespace, ctx: CliContext) -> int:
    since = _parse_since(args.since)

    if args.by == "rolle":
        rows = stats.roll_usage(RollStore())
        if args.json:
            ctx.out(json.dumps([dataclasses.asdict(r) for r in rows], ensure_ascii=False, indent=2))
        else:
            _roll_table(ctx, rows)
        return 0

    with HistoryStore(paths.history_db_path()) as history:
        rows = stats.usage_by(history, args.by, since=since)
    total = stats.totals(rows)
    if args.json:
        data = [dataclasses.asdict(r) for r in rows]
        data.append(dataclasses.asdict(total))
        ctx.out(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        _usage_table(ctx, rows, total)
    return 0
