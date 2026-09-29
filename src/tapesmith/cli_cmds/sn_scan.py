"""Plugin-Befehl 'p12 sn-scan': Seriennummer vom Foto des Herstelleraufklebers lesen."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tapesmith.cli_cmds.base import CliContext, add_print_options
from tapesmith.errors import EXIT_ERROR, EXIT_OK, explain
from tapesmith.integrations.cliprint import print_one, run_guarded
from tapesmith.integrations.codescan import SerialCandidate, scan
from tapesmith.render.zxing import DecoderUnavailable
from tapesmith.i18n import N_, _t

COMMAND = "sn-scan"
HELP = N_("Seriennummer vom Foto des Herstelleraufklebers lesen (Barcode/DataMatrix/QR)")


def register(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("bild", type=Path, metavar=_t("BILD"), help=_t("Bilddatei des Aufklebers"))
    parser.add_argument("--alle", action="store_true", help=_t("alle erkannten Kandidaten mit Punkten und Grund"))
    parser.add_argument("--json", action="store_true", help=_t("Ergebnis als JSON"))
    parser.add_argument(
        "--print", action="store_true", dest="do_print",
        help=_t("erkannte Seriennummer direkt über die Vorlage 'datentraeger' drucken"),
    )
    parser.add_argument("--host", default=None, help=_t("Wert für das Feld Host der Vorlage datentraeger"))
    parser.add_argument("--slot", default=None, help=_t("Wert für das Feld Slot der Vorlage datentraeger"))
    add_print_options(parser)


def _candidate_json(candidate: SerialCandidate) -> dict:
    return {
        "serial": candidate.serial,
        "score": candidate.score,
        "reason": candidate.reason,
        "text": candidate.hit.text,
        "format": candidate.hit.format,
    }


def _read_image(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise ValueError(_t("Bild nicht lesbar: {exc}", exc=exc)) from exc


def _run(args: argparse.Namespace, ctx: CliContext) -> int:
    data = _read_image(args.bild)
    try:
        result = scan(data)
    except DecoderUnavailable as exc:
        ctx.err(str(exc))
        ctx.err(_t("Hinweis: {hint}", hint=explain(exc).hint))
        return EXIT_ERROR

    if args.json:
        body = {
            "width": result.width,
            "height": result.height,
            "candidates": [_candidate_json(c) for c in result.candidates],
            "best": result.best.serial if result.best else None,
        }
        ctx.out(json.dumps(body, ensure_ascii=False))
    elif args.alle:
        for candidate in result.candidates:
            ctx.out(f"{candidate.serial}\t{candidate.score}\t{candidate.reason}")
    elif result.best is not None:
        ctx.out(result.best.serial)

    if result.best is None:
        ctx.err(_t("Keine Seriennummer erkannt ({count} Codes gefunden)", count=len(result.hits)))
        return EXIT_ERROR

    if args.do_print:
        values = {"sn": result.best.serial}
        if args.host:
            values["host"] = args.host
        if args.slot:
            values["slot"] = args.slot
        return print_one(ctx, args, "datentraeger", values)
    return EXIT_OK


def run(args: argparse.Namespace, ctx: CliContext) -> int:
    return run_guarded(ctx, lambda: _run(args, ctx))
