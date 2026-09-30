"""Plugin-Befehl 'tapesmith ka': Kleinanzeigen-Artikel-Tracking.

Unterbefehle: `neu`, `list`, `reserviert`, `verkauft`, `frei`, `print`. Gedruckt wird nur über
`integrations.cliprint.print_one` (Etikett `ka-artikel` bzw. das vorhandene `reserviert`).
"""

from __future__ import annotations

import argparse
import dataclasses
import json
from datetime import date, datetime

import httpx

from tapesmith import numbering
from tapesmith.cli_cmds.base import CliContext, add_print_options
from tapesmith.integrations import kleinanzeigen as ka
from tapesmith.integrations import settings
from tapesmith.integrations.cliprint import check_rows, print_one, run_guarded
from tapesmith.numbering import NumberRanges
from tapesmith.i18n import N_, _t

COMMAND = "ka"
HELP = N_("Kleinanzeigen-Artikel verwalten und beschriften")

# Für Tests: eigener Transport für den Kurz-Link-Dienst statt echtem Netz.
TRANSPORT: httpx.BaseTransport | None = None


def register(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="ka_cmd", required=True)

    p_neu = sub.add_parser("neu", help=_t("neuen Artikel anlegen"))
    p_neu.add_argument("titel")
    p_neu.add_argument("--preis", default="", help=_t("frei, z. B. '25 €' oder 'VB 40'"))
    p_neu.add_argument("--anzeige", metavar="URL", help=_t("Adresse der Kleinanzeige"))
    p_neu.add_argument("--ort", default="", help=_t("Kiste, Regal"))
    p_neu.add_argument("--notiz", default="")
    p_neu.add_argument("--print", dest="do_print", action="store_true",
                       help=_t("danach sofort das Artikel-Etikett drucken"))
    add_print_options(p_neu)

    p_list = sub.add_parser("list", help=_t("Artikel auflisten"))
    p_list.add_argument("--status", choices=ka.STATUSES)
    p_list.add_argument("--query", default="")
    p_list.add_argument("--json", action="store_true")

    p_res = sub.add_parser("reserviert", help=_t("Artikel reservieren"))
    p_res.add_argument("id")
    p_res.add_argument("name")
    p_res.add_argument("--bis", required=True, metavar=_t("TT.MM.JJJJ"), help=_t("Frist der Reservierung"))
    p_res.add_argument("--print", dest="do_print", action="store_true",
                       help=_t("danach sofort das Etikett 'reserviert' drucken"))
    add_print_options(p_res)

    p_verk = sub.add_parser("verkauft", help=_t("Artikel als verkauft eintragen"))
    p_verk.add_argument("id")
    p_verk.add_argument("name")
    p_verk.add_argument("--am", metavar=_t("TT.MM.JJJJ"), help=_t("Verkaufsdatum (Standard: heute)"))

    p_frei = sub.add_parser("frei", help=_t("Reservierung aufheben (zurück auf verfügbar)"))
    p_frei.add_argument("id")

    p_print = sub.add_parser("print", help=_t("Etikett eines Artikels drucken"))
    p_print.add_argument("id")
    p_print.add_argument("--reserviert", action="store_true",
                         help=_t("das Etikett 'reserviert' statt 'ka-artikel' drucken"))
    add_print_options(p_print)


def _parse_date(text: str) -> date:
    try:
        return datetime.strptime(text, "%d.%m.%Y").date()
    except ValueError:
        raise ValueError(_t("Datum '{text}' nicht lesbar (TT.MM.JJJJ)", text=text)) from None


def _ranges(ctx: CliContext) -> NumberRanges:
    return NumberRanges(numbering.numbering_dir(ctx.load_config()) / numbering.FILE_NAME)


def _require(store: ka.KaStore, ka_id: str) -> ka.Artikel:
    art = store.get(ka_id)
    if art is None:
        raise ValueError(_t("Kleinanzeigen-Artikel '{ka_id}' gibt es nicht", ka_id=ka_id))
    return art


def _print_artikel(ctx: CliContext, args: argparse.Namespace, art: ka.Artikel) -> int:
    data = settings.load_settings()
    real_print = not (getattr(args, "dry_run", False) or getattr(args, "preview", None))
    label, warnings = ka.article_label(data, art, sync=real_print, transport=TRANSPORT)
    for warning in warnings:
        ctx.err(_t("Hinweis: {warning}", warning=warning))
    return print_one(ctx, args, label["template"], label["values"])


def _print_reserved(ctx: CliContext, args: argparse.Namespace, art: ka.Artikel) -> int:
    label = ka.reserved_label(art)
    return print_one(ctx, args, label["template"], label["values"])


ROLLBACK_REASON = N_("Etikett nicht erzeugt (ka neu --print)")


def _run_neu(args: argparse.Namespace, ctx: CliContext) -> int:
    data = settings.load_settings()
    ranges = _ranges(ctx)
    fields = {"titel": args.titel, "preis": args.preis, "anzeige": args.anzeige, "ort": args.ort,
              "notiz": args.notiz}
    do_print = getattr(args, "do_print", False)
    with ka.KaStore() as store:
        if do_print:
            # Erst das Etikett rendern (ohne Netz, ohne Token), dann die Nummer vergeben.
            draft = store.draft(ranges, data, **fields)
            label, _warnings = ka.article_label(data, draft, sync=False)
            code = check_rows(ctx, label["template"], [label["values"]])
            if code != 0:
                ctx.err(_t("Artikel nicht angelegt, keine Nummer vergeben"))
                return code
        art = store.add(ranges, data, **fields)
        ctx.out(art.id)
        if not do_print:
            return 0
        try:
            code = _print_artikel(ctx, args, art)
        except BaseException:
            store.discard(ranges, data, art.id, _t(ROLLBACK_REASON))
            ctx.err(_t("{id} zurückgenommen (Nummer verworfen)", id=art.id))
            raise
        if code != 0:
            store.discard(ranges, data, art.id, _t(ROLLBACK_REASON))
            ctx.err(_t("{id} zurückgenommen (Nummer verworfen)", id=art.id))
        return code


def _status_line(art: ka.Artikel) -> str:
    if art.status == "reserviert":
        return _t("{id}  {status:<10}  {titel}  ·  {name} bis {datum}", id=art.id, status=art.status, titel=art.titel, name=art.name, datum=art.datum)
    if art.status == "verkauft":
        return f"{art.id}  {art.status:<10}  {art.titel}  ·  {art.name} am {art.datum}"
    return f"{art.id}  {art.status:<10}  {art.titel}"


def _run_list(args: argparse.Namespace, ctx: CliContext) -> int:
    with ka.KaStore() as store:
        items = store.list(status=args.status, query=args.query)
    if args.json:
        ctx.out(json.dumps([dataclasses.asdict(a) for a in items], ensure_ascii=False, indent=2))
        return 0
    if not items:
        ctx.out(_t("Keine Artikel"))
        return 0
    for art in items:
        ctx.out(_status_line(art))
    return 0


def _run_reserviert(args: argparse.Namespace, ctx: CliContext) -> int:
    bis = _parse_date(args.bis)
    with ka.KaStore() as store:
        art = store.reserve(args.id, args.name, bis)
    ctx.out(_t("{id} reserviert für {name} bis {datum}", id=art.id, name=art.name, datum=art.datum))
    if getattr(args, "do_print", False):
        return _print_reserved(ctx, args, art)
    return 0


def _run_verkauft(args: argparse.Namespace, ctx: CliContext) -> int:
    on = _parse_date(args.am) if args.am else datetime.now().date()
    with ka.KaStore() as store:
        art = store.sell(args.id, args.name, on)
    ctx.out(_t("{id} verkauft an {name} am {datum}", id=art.id, name=art.name, datum=art.datum))
    return 0


def _run_frei(args: argparse.Namespace, ctx: CliContext) -> int:
    with ka.KaStore() as store:
        art = store.release(args.id)
    ctx.out(_t("{id} wieder verfügbar", id=art.id))
    return 0


def _run_print(args: argparse.Namespace, ctx: CliContext) -> int:
    with ka.KaStore() as store:
        art = _require(store, args.id)
    if args.reserviert:
        return _print_reserved(ctx, args, art)
    return _print_artikel(ctx, args, art)


def _dispatch(args: argparse.Namespace, ctx: CliContext) -> int:
    cmd = args.ka_cmd
    if cmd == "neu":
        return _run_neu(args, ctx)
    if cmd == "list":
        return _run_list(args, ctx)
    if cmd == "reserviert":
        return _run_reserviert(args, ctx)
    if cmd == "verkauft":
        return _run_verkauft(args, ctx)
    if cmd == "frei":
        return _run_frei(args, ctx)
    if cmd == "print":
        return _run_print(args, ctx)
    raise ValueError(_t("Unbekannter Unterbefehl 'ka {cmd}'", cmd=cmd))


def run(args: argparse.Namespace, ctx: CliContext) -> int:
    return run_guarded(ctx, lambda: _dispatch(args, ctx))
