"""Plugin-Befehl 'p12 batterie': Batteriestände aus Home Assistant auflisten, lokale
Typzuordnung pflegen, Batterie- und Wartungsetiketten drucken, optional ein HA-To-do anlegen.

Kein echter HA-Aufruf standardmäßig: `TRANSPORT` ist injizierbar (Tests ersetzen es).
"""

from __future__ import annotations

import argparse
import dataclasses
import json
from datetime import date, datetime

import httpx

from tapesmith.cli_cmds.base import CliContext, add_print_options
from tapesmith.errors import EXIT_ERROR, EXIT_OK
from tapesmith.integrations import homeassistant as ha
from tapesmith.integrations import settings
from tapesmith.integrations.cliprint import add_series_options, print_one, print_rows, run_guarded
from tapesmith.integrations.errors import NotConfigured
from tapesmith.i18n import N_, _t

COMMAND = "batterie"
HELP = N_("Batterie- und Wartungsetiketten aus Home Assistant auflisten und drucken")

# Für Tests: eigenen Transport einsetzen, ohne echtes Netz aufzurufen.
TRANSPORT: httpx.BaseTransport | None = None


def register(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="batterie_cmd", required=True)

    p_list = sub.add_parser("list", help=_t("Geräte mit Batterie auflisten"))
    p_list.add_argument("--unter", type=int, metavar="N",
                        help=_t("nur Geräte unter N %% (Standard: homeassistant.battery_below)"))
    p_list.add_argument("--json", action="store_true", help=_t("Ausgabe als JSON"))

    p_typ = sub.add_parser("typ", help=_t("Batterietyp lokal zuordnen"))
    p_typ.add_argument("entity_id")
    p_typ.add_argument("typ", help=_t("Batterietyp, '-' entfernt die Zuordnung"))

    p_print = sub.add_parser("print", help=_t("Batterie-Etikett(en) drucken"))
    p_print.add_argument("entity_id", nargs="+")
    p_print.add_argument("--datum", metavar=_t("TT.MM.JJJJ"), help=_t("Standard: heute"))
    add_series_options(p_print, template="batterie")

    p_wartung = sub.add_parser("wartung", help=_t("Wartungsetikett drucken"))
    p_wartung.add_argument("was")
    p_wartung.add_argument("--intervall", type=int, required=True, metavar=_t("MONATE"))
    p_wartung.add_argument("--datum", metavar=_t("TT.MM.JJJJ"), help=_t("Standard: heute"))
    p_wartung.add_argument("--notiz", default="")
    p_wartung.add_argument("--todo", action="store_true",
                           help=_t("nach erfolgreichem Druck ein Home-Assistant-To-do anlegen"))
    p_wartung.add_argument("--nur-todo", action="store_true",
                           help=_t("nur das To-do anlegen, ohne zu drucken"))
    add_print_options(p_wartung)


def _client(data: dict) -> ha.HaClient:
    return ha.HaClient.from_settings(data, transport=TRANSPORT)


def _parse_datum(text: str | None) -> date:
    if not text:
        return date.today()
    try:
        return datetime.strptime(text, "%d.%m.%Y").date()
    except ValueError as exc:
        raise ValueError(_t("Datum '{text}' nicht lesbar (TT.MM.JJJJ)", text=text)) from exc


def _stand_text(dev: ha.BatteryDevice) -> str:
    if dev.level is not None:
        return f"{dev.level} %"
    return "schwach" if dev.low else "-"


def _run_list(args: argparse.Namespace, ctx: CliContext) -> int:
    data = settings.load_settings()
    client = _client(data)
    types = ha.BatteryTypes()
    below = args.unter if args.unter is not None else data["homeassistant"].get("battery_below", 101)
    devices = ha.parse_devices(client.batteries(), types, below=below)

    if args.json:
        ctx.out(json.dumps([dataclasses.asdict(d) for d in devices], ensure_ascii=False, indent=2))
        return EXIT_OK
    if not devices:
        ctx.out(_t("Keine Geräte gefunden"))
        return EXIT_OK
    for dev in devices:
        ctx.out(f"{dev.device}  {dev.area}  {_stand_text(dev)}  {dev.battery_type or '-'}  "
                f"{dev.type_source or '-'}")
    return EXIT_OK


def _run_typ(args: argparse.Namespace, ctx: CliContext) -> int:
    value = None if args.typ == "-" else args.typ
    ha.BatteryTypes().set(args.entity_id, value)
    ctx.out(f"{args.entity_id}: {value or '(entfernt)'}")
    return EXIT_OK


def _run_print(args: argparse.Namespace, ctx: CliContext) -> int:
    data = settings.load_settings()
    client = _client(data)
    types = ha.BatteryTypes()
    by_id = {d.entity_id: d for d in ha.parse_devices(client.batteries(), types, below=101)}
    day = _parse_datum(args.datum)

    rows = []
    for entity_id in args.entity_id:
        dev = by_id.get(entity_id)
        if dev is None:
            ctx.err(_t("Gerät '{entity_id}' nicht gefunden", entity_id=entity_id))
            continue
        rows.append(ha.battery_values(dev, day=day))
    if not rows:
        ctx.err(_t("Keine druckbaren Zeilen"))
        return EXIT_ERROR
    return print_rows(ctx, args, args.template, rows)


def _run_wartung(args: argparse.Namespace, ctx: CliContext) -> int:
    data = settings.load_settings()
    day = _parse_datum(args.datum)
    values = ha.maintenance_values(args.was, day=day, months=args.intervall, note=args.notiz)

    def add_todo() -> None:
        entity_id = data["homeassistant"].get("todo_entity")
        if not entity_id:
            raise NotConfigured("Home Assistant",
                                _t("To-do-Liste nicht eingerichtet: homeassistant.todo_entity fehlt"))
        client = _client(data)
        due = ha.due_date(day, args.intervall)
        client.add_todo(entity_id, _t("Wartung: {was}", was=args.was), due=due, description=args.notiz)
        ctx.out(_t("To-do angelegt"))

    if args.nur_todo:
        add_todo()
        return EXIT_OK

    on_printed = add_todo if args.todo else None
    return print_one(ctx, args, "wartung", values, on_printed=on_printed)


def _dispatch(args: argparse.Namespace, ctx: CliContext) -> int:
    cmd = args.batterie_cmd
    if cmd == "list":
        return _run_list(args, ctx)
    if cmd == "typ":
        return _run_typ(args, ctx)
    if cmd == "print":
        return _run_print(args, ctx)
    if cmd == "wartung":
        return _run_wartung(args, ctx)
    raise ValueError(_t("Unbekannter Unterbefehl 'batterie {cmd}'", cmd=cmd))


def run(args: argparse.Namespace, ctx: CliContext) -> int:
    return run_guarded(ctx, lambda: _dispatch(args, ctx))
