"""`p12 reprint`: ein Label aus dem Verlauf erneut drucken.

Nicht sensible Einträge werden aus dem gespeicherten Kopfbild gedruckt; Kopien, Kette und
Jobaufteilung plant die Pipeline wieder genauso wie beim Original. Sensible Vorlagen-Einträge
haben kein Kopfbild; ihre verdeckten Felder müssen neu eingegeben werden (`--prompt FELD`).

Die eigentliche Logik steckt in `tapesmith.reprint` (Kern-API ohne CLI/Qt); dieses Modul sammelt
nur die Kommandozeilenoptionen ein und übersetzt `MissingSecrets` in die bisherige Meldung.
"""

import argparse
import getpass

from tapesmith import paths
from tapesmith.cli_cmds import base as cmd_base
from tapesmith.cli_cmds.base import CliContext, add_print_options, parse_sets
from tapesmith.history import HistoryStore
from tapesmith.reprint import MissingSecrets, load_entry, prepare_reprint
from tapesmith.templates.model import TemplateError
from tapesmith.i18n import N_, _t

COMMAND = "reprint"
HELP = N_("Label aus dem Verlauf erneut drucken")
GETPASS = getpass.getpass


def register(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("target", help=_t("'last' oder die ID aus 'p12 history'"))
    parser.add_argument("--prompt", action="append", default=[], metavar=_t("FELD"),
                        help=_t("sensibles Feld verdeckt neu eingeben (empfohlen)"))
    parser.add_argument("--set", action="append", default=[], metavar=_t("FELD=WERT"),
                        help=_t("Feldwert setzen (landet in der Shell-History, für Sensibles --prompt)"))
    add_print_options(parser)
    parser.set_defaults(copies=None)  # "nicht angegeben" -> Kopien des Originals


def run(args: argparse.Namespace, ctx: CliContext) -> int:
    sets = parse_sets(args.set)
    for field_id in args.prompt:
        sets[field_id] = GETPASS(f"{field_id}: ")

    # `prepare_reprint` erst aufrufen, während der Store noch offen ist (liest ggf. das Kopfbild);
    # `emit_labels` danach außerhalb des `with` (öffnet für den Verlaufseintrag selbst einen Store).
    with HistoryStore(paths.history_db_path()) as store:
        entry = load_entry(store, args.target)
        try:
            job = prepare_reprint(store, entry, ctx.load_profile(), sets=sets,
                                  copies=args.copies, chain=True if args.chain else None, source="cli")
        except MissingSecrets as exc:
            field_id = exc.fields[0]
            raise TemplateError(_t("Feld '{field_id}' ist sensibel und muss neu eingegeben werden (--prompt {field_id} oder --set {field_id}=…)", field_id=field_id)) from exc
        if job.from_image and (args.prompt or args.set):
            ctx.err(_t("Hinweis: --prompt/--set wirken nur bei sensiblen Vorlagen, gedruckt wird das gespeicherte Bild"))

    if cmd_base.emit_labels(ctx, job.labels, job.meta, job.result, copies=job.copies, chain=job.chain):
        job.commit_counters()
    return 0
