"""Plugin-Befehl 'p12 garantie': Garantie-Etikett aus Paperless-Rechnungen suchen und drucken.

Kein echter Netzzugriff standardmäßig: `TRANSPORT`/`SHORTLINK_TRANSPORT` sind injizierbar (Tests
ersetzen sie).
"""

from __future__ import annotations

import argparse
from datetime import datetime

import httpx

from tapesmith.cli_cmds.base import CliContext, add_print_options
from tapesmith.integrations import paperless, settings, shortlink
from tapesmith.integrations.cliprint import print_one, run_guarded
from tapesmith.i18n import N_, _t

COMMAND = "garantie"
HELP = N_("Garantie-Etikett aus Paperless-Rechnungen suchen und drucken")

# Für Tests: eigenen Transport einsetzen, ohne echtes Netz aufzurufen.
TRANSPORT: httpx.BaseTransport | None = None
SHORTLINK_TRANSPORT: httpx.BaseTransport | None = None

_DATE_ARG_FORMAT = "%d.%m.%Y"
_GERAET_MAX_LEN = 20


def register(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="garantie_cmd", required=True)

    s = sub.add_parser("suche", help=_t("Rechnungen in Paperless durchsuchen"))
    s.add_argument("text", nargs="?", default="", help=_t("Suchtext"))
    s.add_argument("--haendler", default="", metavar="NAME")
    s.add_argument("--von", metavar=_t("TT.MM.JJJJ"))
    s.add_argument("--bis", metavar=_t("TT.MM.JJJJ"))

    p = sub.add_parser("print", help=_t("Garantie-Etikett für ein Dokument drucken"))
    p.add_argument("doc_id", type=int)
    p.add_argument("--monate", type=int, metavar="N", help=_t("Laufzeit in Monaten (überstimmt Paperless)"))
    p.add_argument("--geraet", metavar="TEXT")
    add_print_options(p)


def _parse_arg_date(text: str | None, label: str):
    if not text:
        return None
    try:
        return datetime.strptime(text, _DATE_ARG_FORMAT).date()
    except ValueError:
        raise ValueError(_t("{label} '{text}' nicht lesbar (TT.MM.JJJJ)", label=label, text=text)) from None


def _run_suche(args: argparse.Namespace, ctx: CliContext) -> int:
    data = settings.load_settings()
    von = _parse_arg_date(args.von, "--von")
    bis = _parse_arg_date(args.bis, "--bis")
    with paperless.PaperlessClient.from_settings(data, transport=TRANSPORT) as client:
        hits = client.search(args.text, correspondent=args.haendler, date_from=von, date_to=bis)
    if not hits:
        ctx.out(_t("Keine Treffer"))
        return 0
    ctx.out(_t("ID\tDatum\tKorrespondent\tTitel"))
    for hit in hits:
        ctx.out(f"{hit.id}\t{hit.created}\t{hit.correspondent or ''}\t{hit.title}")
    return 0


def _run_print(args: argparse.Namespace, ctx: CliContext) -> int:
    data = settings.load_settings()
    with paperless.PaperlessClient.from_settings(data, transport=TRANSPORT) as client:
        hit = client.document(args.doc_id)
    w = paperless.warranty(hit, data["paperless"]["warranty_fields"], months=args.monate)

    link_warnings: list[str] = []
    if shortlink.configured(data):
        link = shortlink.link_for(data, f"DOC-{args.doc_id}", hit.url, note=hit.title,
                                  transport=SHORTLINK_TRANSPORT)
    else:
        link = hit.url
        link_warnings.append(_t("QR enthält die lange Paperless-Adresse"))

    geraet = (args.geraet or hit.title)[:_GERAET_MAX_LEN]
    values, warnings = paperless.warranty_values(w, geraet=geraet, link=link)
    warnings = warnings + link_warnings

    quelle_suffix = f" ({w.quelle_ende})" if w.quelle_ende else ""
    ctx.out(_t("Garantie bis {ende}{quelle_suffix}", ende=values['ende'], quelle_suffix=quelle_suffix))
    for warning in warnings:
        ctx.out(_t("Hinweis: {warning}", warning=warning))

    return print_one(ctx, args, "garantie-qr", values)


def run(args: argparse.Namespace, ctx: CliContext) -> int:
    def go() -> int:
        if args.garantie_cmd == "suche":
            return _run_suche(args, ctx)
        if args.garantie_cmd == "print":
            return _run_print(args, ctx)
        raise ValueError(_t("Unbekannter Unterbefehl 'garantie {garantie_cmd}'", garantie_cmd=args.garantie_cmd))

    return run_guarded(ctx, go)
