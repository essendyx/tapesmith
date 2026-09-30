"""Plugin-Befehl 'tapesmith asn': Paperless-ASN-Serien reservieren, drucken und verwerfen.

Kein echter Netzzugriff standardmäßig: `TRANSPORT` ist injizierbar (Tests ersetzen es), Standard
ist ein echter httpx-Transport über `PaperlessClient.from_settings`.
"""

from __future__ import annotations

import argparse

import httpx

from tapesmith import numbering
from tapesmith.cli_cmds.base import CliContext
from tapesmith.integrations import paperless, settings
from tapesmith.integrations.cliprint import add_series_options, print_rows, run_guarded
from tapesmith.i18n import N_, _t

COMMAND = "asn"
HELP = N_("Paperless-ASN-Serien reservieren, drucken und verwerfen")

# Für Tests: eigenen Transport einsetzen, ohne echtes Netz aufzurufen.
TRANSPORT: httpx.BaseTransport | None = None


def register(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="asn_cmd", required=True)

    sub.add_parser("next", help=_t("nächste ASN aus Paperless und lokalem Nummernkreis anzeigen"))

    r = sub.add_parser("reserve", help=_t("ASN-Nummern reservieren, wahlweise sofort als Serie drucken"))
    r.add_argument("count", type=int, help=_t("Anzahl Nummern (1..500)"))
    r.add_argument("--print", dest="do_print", action="store_true",
                   help=_t("reservierte Nummern sofort als Serie drucken (Standard: Kettendruck)"))
    add_series_options(r, template="asn")

    v = sub.add_parser("void", help=_t("reservierte ASN verwerfen (Fehldruck)"))
    v.add_argument("asn")
    v.add_argument("--grund", required=True)


def _ranges(ctx: CliContext) -> numbering.NumberRanges:
    cfg = ctx.load_config()
    return numbering.NumberRanges(numbering.numbering_dir(cfg) / numbering.FILE_NAME)


def _client(data: dict) -> paperless.PaperlessClient:
    return paperless.PaperlessClient.from_settings(data, transport=TRANSPORT)


def _run_next(ctx: CliContext) -> int:
    data = settings.load_settings()
    ranges = _ranges(ctx)
    with _client(data) as client:
        paperless_next = client.next_asn()
    try:
        local = ranges.peek(data["paperless"]["asn_range"])
    except KeyError:
        local = _t("noch kein Nummernkreis angelegt")
    next_text = paperless.peek_next_asn(ranges, data, paperless_next)
    ctx.out(_t("Paperless: nächste ASN {paperless_next}", paperless_next=paperless_next))
    ctx.out(_t("Lokal: {local}", local=local))
    ctx.out(_t("Nächste Nummer: {next_text}", next_text=next_text))
    ctx.out(paperless.SCAN_TEST_HINT)
    return 0


def _dry_run_numbers(data: dict, ranges: numbering.NumberRanges, count: int) -> list[str]:
    section = data["paperless"]
    with _client(data) as client:
        paperless_next = client.next_asn()
    start_text = paperless.peek_next_asn(ranges, data, paperless_next)
    start_n = paperless.asn_number(start_text, section["asn_prefix"])
    return [paperless.asn_text(section["asn_prefix"], section["asn_width"], start_n + i) for i in range(count)]


def _run_reserve(args: argparse.Namespace, ctx: CliContext) -> int:
    data = settings.load_settings()
    ranges = _ranges(ctx)

    if args.dry_run:  # mit und ohne --print: nur anzeigen, nichts reservieren
        for number in _dry_run_numbers(data, ranges, args.count):
            ctx.out(number)
        return 0

    with _client(data) as client:
        numbers = paperless.reserve_asns(client, ranges, data, args.count)

    if not args.do_print:
        for number in numbers:
            ctx.out(number)
        return 0

    args.chain = True  # Standard-Kettendruck für ASN-Serien.
    rows = [{"asn": number} for number in numbers]
    return print_rows(ctx, args, "asn", rows)


def _run_void(args: argparse.Namespace, ctx: CliContext) -> int:
    data = settings.load_settings()
    ranges = _ranges(ctx)
    paperless.void_asn(ranges, data, args.asn, args.grund)
    ctx.out(_t("ASN '{asn}' verworfen: {grund}", asn=args.asn, grund=args.grund))
    return 0


def run(args: argparse.Namespace, ctx: CliContext) -> int:
    def go() -> int:
        if args.asn_cmd == "next":
            return _run_next(ctx)
        if args.asn_cmd == "reserve":
            return _run_reserve(args, ctx)
        if args.asn_cmd == "void":
            return _run_void(args, ctx)
        raise ValueError(_t("Unbekannter Unterbefehl 'asn {asn_cmd}'", asn_cmd=args.asn_cmd))

    return run_guarded(ctx, go)
