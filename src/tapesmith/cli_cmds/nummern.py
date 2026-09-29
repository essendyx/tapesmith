"""Plugin-Befehl 'p12 nummern': zentrale Nummernkreise anlegen, reservieren, verwerfen,
exportieren/importieren."""

import argparse
from pathlib import Path

from tapesmith import numbering
from tapesmith.i18n import N_, _t

COMMAND = "nummern"
HELP = N_("Nummernkreise anlegen, reservieren, verwerfen, exportieren/importieren")


def register(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="nummern_cmd", required=True)

    sub.add_parser("list", help=_t("alle Nummernkreise"))

    d = sub.add_parser("define", help=_t("neuen Nummernkreis anlegen"))
    d.add_argument("key")
    d.add_argument("--start", type=int, default=1)
    d.add_argument("--prefix", default="")
    d.add_argument("--width", type=int, default=0)

    r = sub.add_parser("reserve", help=_t("Nummern reservieren"))
    r.add_argument("key")
    r.add_argument("--count", type=int, default=1)

    v = sub.add_parser("void", help=_t("vergebene Nummer verwerfen"))
    v.add_argument("key")
    v.add_argument("number")
    v.add_argument("--grund", required=True)

    e = sub.add_parser("export", help=_t("alle Nummernkreise als JSON exportieren"))
    e.add_argument("file", type=Path)

    i = sub.add_parser("import", help=_t("Nummernkreise aus JSON übernehmen"))
    i.add_argument("file", type=Path)


def run(args: argparse.Namespace, ctx) -> int:
    cfg = ctx.load_config()
    ranges = numbering.NumberRanges(numbering.numbering_dir(cfg) / numbering.FILE_NAME)

    try:
        if args.nummern_cmd == "list":
            for r in ranges.list():
                ctx.out(_t("{key}: nächste {format} (Präfix '{prefix}', Breite {width})", key=r.key, format=r.format(r.next), prefix=r.prefix, width=r.width))
            return 0

        if args.nummern_cmd == "define":
            r = ranges.define(args.key, start=args.start, prefix=args.prefix, width=args.width)
            ctx.out(_t("Nummernkreis '{key}' angelegt, erste Nummer {format}", key=r.key, format=r.format(r.next)))
            return 0

        if args.nummern_cmd == "reserve":
            for number in ranges.reserve(args.key, args.count):
                ctx.out(number)
            return 0

        if args.nummern_cmd == "void":
            ranges.void(args.key, args.number, args.grund)
            ctx.out(_t("Nummer '{number}' verworfen: {grund}", number=args.number, grund=args.grund))
            return 0

        if args.nummern_cmd == "export":
            ranges.export_json(args.file)
            ctx.out(_t("Exportiert nach {file}", file=args.file))
            return 0

        if args.nummern_cmd == "import":
            for line in ranges.import_json(args.file):
                ctx.out(line)
            return 0
    except (KeyError, ValueError) as exc:
        ctx.err(_t("Fehler: {exc}", exc=exc))
        return 1

    raise ValueError(_t("Unbekannter Unterbefehl '{nummern_cmd}'", nummern_cmd=args.nummern_cmd))
