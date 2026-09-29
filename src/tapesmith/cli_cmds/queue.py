"""Plugin-Befehl 'p12 queue': Druckwarteschlange des Druckdienstes anzeigen und steuern."""

from __future__ import annotations

import argparse
import json

from tapesmith.cli_cmds import base as cmd_base
from tapesmith.cli_cmds.base import positive_int
from tapesmith.errors import EXIT_ERROR, EXIT_OK
from tapesmith.ipc.backend import QueueSnapshot, make_backend
from tapesmith.i18n import N_, _t

COMMAND = "queue"
HELP = N_("Druckwarteschlange des Druckdienstes anzeigen und steuern")

NEEDS_DAEMON = N_("Warteschlange braucht den Druckdienst (p12 daemon start)")


class _NoDaemon:
    """Platzhalter, wenn kein Dienst erreichbar ist (die Warteschlange gibt es nur im Dienst)."""

    kind = "local"

    def __init__(self, reason: str):
        self.fallback_reason = reason

    def queue_ops(self):
        return None

    def close(self) -> None:
        pass


def register(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="queue_cmd", required=True)
    ls = sub.add_parser("list", help=_t("Aufträge auflisten"))
    ls.add_argument("--all", action="store_true", help=_t("auch fertige/abgebrochene Aufträge"))
    ls.add_argument("--json", action="store_true", help=_t("als JSON ausgeben"))
    c = sub.add_parser("cancel", help=_t("Auftrag abbrechen"))
    c.add_argument("id", type=int)
    d = sub.add_parser("dup", help=_t("Auftrag duplizieren"))
    d.add_argument("id", type=int)
    m = sub.add_parser("move", help=_t("Auftrag an Position POS verschieben (1 = als Nächstes)"))
    m.add_argument("id", type=int)
    m.add_argument("pos", type=positive_int)
    r = sub.add_parser("retry", help=_t("jetzt erneut versuchen (ohne ID: alle wartenden)"))
    r.add_argument("id", type=int, nargs="?")
    sub.add_parser("pause", help=_t("Warteschlange anhalten"))
    sub.add_parser("resume", help=_t("Warteschlange fortsetzen"))


def _backend(ctx):
    if cmd_base.BACKEND_FACTORY is not None:
        return cmd_base.BACKEND_FACTORY(ctx, None)
    return make_backend(ctx.load_config(), ctx.load_profile(), client="cli", local_factory=_NoDaemon,
                        allow_spawn=True)


def _time(value) -> str:
    return value.strftime("%d.%m. %H:%M:%S") if value is not None else "-"


def _snapshot_dict(snap: QueueSnapshot) -> dict:
    return {"jobs": [job.to_dict() for job in snap.jobs], "paused": snap.paused, "auto_retry": snap.auto_retry,
            "next_try": snap.next_try.isoformat(timespec="seconds") if snap.next_try else None,
            "probe": snap.probe, "waiting_reason": snap.waiting_reason}


def _print_list(ctx, snap: QueueSnapshot) -> None:
    head = [_t("Warteschlange: {count} Auftrag/Aufträge", count=len(snap.jobs))]
    if snap.paused:
        head.append("pausiert")
    if not snap.auto_retry:
        head.append(_t("Auto-Nachdruck aus"))
    if snap.waiting_reason:
        head.append(snap.waiting_reason)
    if snap.next_try is not None:
        head.append(_t("nächster Versuch {time}", time=_time(snap.next_try)))
    ctx.out(" · ".join(head))
    if not snap.jobs:
        ctx.out(_t("(leer)"))
        return
    ctx.out(_t("{value:>5}  {value2:<11}  {value3:>8}  {value4:<16}  {value5:<8}  Titel", value='#id', value2='Zustand', value3='Versuche', value4='nächster Versuch', value5='Quelle'))
    for job in snap.jobs:
        ctx.out(f"{'#' + str(job.id):>5}  {job.state:<11}  {job.attempts:>8}  {_time(job.next_try):<16}  "
                f"{job.source:<8}  {job.title}")


def run(args: argparse.Namespace, ctx) -> int:
    backend = _backend(ctx)
    try:
        ops = backend.queue_ops()
        if ops is None:
            if backend.fallback_reason:
                ctx.err(_t("Hinweis: {fallback_reason}", fallback_reason=backend.fallback_reason))
            ctx.err(_t(NEEDS_DAEMON))
            return EXIT_ERROR
        cmd = args.queue_cmd
        if cmd == "list":
            snap = ops.list(include_done=args.all)
            if args.json:
                ctx.out(json.dumps(_snapshot_dict(snap), ensure_ascii=False, indent=2))
            else:
                _print_list(ctx, snap)
            return EXIT_OK
        if cmd == "cancel":
            if not ops.cancel(args.id):
                ctx.err(_t("Auftrag #{id} nicht gefunden oder nicht mehr abbrechbar", id=args.id))
                return EXIT_ERROR
            ctx.out(_t("Auftrag #{id} abgebrochen", id=args.id))
            return EXIT_OK
        if cmd == "dup":
            new_id = ops.duplicate(args.id)
            ctx.out(_t("Auftrag #{id} dupliziert: #{new_id}", id=args.id, new_id=new_id))
            return EXIT_OK
        if cmd == "move":
            ops.move(args.id, args.pos - 1)
            ctx.out(_t("Auftrag #{id} an Position {pos}", id=args.id, pos=args.pos))
            return EXIT_OK
        if cmd == "retry":
            ops.retry(args.id)
            ctx.out(_t("Nachdruck angestoßen") if args.id is None else _t("Auftrag #{id}: Nachdruck angestoßen", id=args.id))
            return EXIT_OK
        if cmd == "pause":
            ops.pause()
            ctx.out(_t("Warteschlange angehalten"))
            return EXIT_OK
        if cmd == "resume":
            ops.resume()
            ctx.out(_t("Warteschlange läuft weiter"))
            return EXIT_OK
        raise ValueError(_t("Unbekannter Unterbefehl '{cmd}'", cmd=cmd))
    finally:
        backend.close()
