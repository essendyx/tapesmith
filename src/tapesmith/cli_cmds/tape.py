"""Plugin-Befehl 'p12 tape': Band wählen, Bandliste anzeigen, Restmeter verwalten.

Rollen gelten je Band: `roll`/`new-roll`/`empty` beziehen sich immer auf das aktuell gewählte Band."""

import argparse

from tapesmith import config
from tapesmith.tape.profiles import current_tape, find_tape, list_tapes
from tapesmith.tape.rolls import ROLL_LENGTH_MM, RollStore
from tapesmith.i18n import N_, _t

COMMAND = "tape"
HELP = N_("Band wählen, Bandliste anzeigen, Restmeter verwalten")


def register(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="tape_cmd", required=True)
    sub.add_parser("list", help=_t("alle Bänder, aktuelles markiert"))

    s = sub.add_parser("set", help=_t("Band auswählen"))
    s.add_argument("id")

    sub.add_parser("roll", help=_t("Restmeter der aktuellen Rolle"))

    n = sub.add_parser("new-roll", help=_t("neue Rolle für das aktuelle Band beginnen"))
    n.add_argument("--length-m", type=float, default=ROLL_LENGTH_MM / 1000, help=_t("Nennlänge in Metern"))

    e = sub.add_parser("empty", help=_t("Rolle war leer (Korrektur), lernt den Längenfaktor"))
    e.add_argument("--at-m", type=float, default=None, help=_t("tatsächliche Länge in Metern (Default: verbraucht)"))


def run(args: argparse.Namespace, ctx) -> int:
    cfg = ctx.load_config()

    if args.tape_cmd == "list":
        current = current_tape(cfg)
        for t in list_tapes():
            marker = "*" if t.id == current.id else " "
            hint = _t(" (dunkel, Codes invertiert)") if t.dark else ""
            ctx.out(f"{marker} {t.id:24} {t.name}{hint}")
        return 0

    if args.tape_cmd == "set":
        try:
            tape = find_tape(args.id)
        except ValueError as exc:
            ctx.err(str(exc))
            return 1
        config.save_config({"tape": {"current": tape.id}})
        ctx.out(_t("Band gesetzt: {name}", name=tape.name))
        ctx.out(_t("Rolle: {summary}", summary=RollStore().summary(tape_id=tape.id)))
        return 0

    tape = current_tape(cfg)
    store = RollStore()

    if args.tape_cmd == "roll":
        ctx.out(f"{tape.name}: {store.summary(tape_id=tape.id)}")
        return 0

    if args.tape_cmd == "new-roll":
        store.new_roll(tape.id, length_mm=args.length_m * 1000)
        ctx.out(f"{tape.name}: {store.summary(tape_id=tape.id)}")
        return 0

    if args.tape_cmd == "empty":
        at_mm = None if args.at_m is None else args.at_m * 1000
        factor = store.mark_empty(at_mm, tape_id=tape.id)
        ctx.out(f"Faktor gelernt: {factor:.2f}".replace(".", ","))
        return 0

    raise ValueError(_t("Unbekannter Unterbefehl '{tape_cmd}'", tape_cmd=args.tape_cmd))
