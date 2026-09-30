"""Plugin-Befehl 'tapesmith backup': Sicherung erstellen, auflisten, wiederherstellen."""

import argparse
from pathlib import Path

from tapesmith import backup as backup_mod
from tapesmith.cli_cmds.base import YES_ANSWERS
from tapesmith.ipc.launcher import daemon_running
from tapesmith.i18n import N_, _t

COMMAND = "backup"
HELP = N_("Zustandsdaten sichern, auflisten, wiederherstellen")

# Dienst-Prüfung (läuft der Druckdienst?), damit `restore` ihn vorher stoppen lässt.
RUNNING_CHECK = daemon_running


def register(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="backup_cmd", required=True)

    c = sub.add_parser("create", help=_t("Sicherung jetzt erstellen"))
    c.add_argument("--dir", type=Path, default=None)

    l = sub.add_parser("list", help=_t("vorhandene Sicherungen auflisten"))
    l.add_argument("--dir", type=Path, default=None)

    r = sub.add_parser("restore", help=_t("Sicherung wiederherstellen"))
    r.add_argument("archive", type=Path)
    r.add_argument("--dry-run", action="store_true")
    r.add_argument("-y", "--yes", action="store_true")


def _confirm(ctx) -> bool:
    if not ctx.stdin_is_tty():
        ctx.err(_t("Rückfrage nötig, mit --yes bestätigen"))
        return False
    print(_t("Vorhandene Zustandsdateien werden vorher gesichert. Wirklich wiederherstellen? [j/N] "),
          end="", file=ctx.stderr, flush=True)
    answer = ctx.stdin.readline().strip().lower()
    if answer not in YES_ANSWERS:
        ctx.err(_t("Abgebrochen"))
        return False
    return True


def run(args: argparse.Namespace, ctx) -> int:
    cfg = ctx.load_config()

    if args.backup_cmd == "create":
        path = backup_mod.create_backup(args.dir, cfg=cfg)
        ctx.out(_t("Sicherung erstellt: {path}", path=path))
        return 0

    if args.backup_cmd == "list":
        directory = args.dir if args.dir is not None else backup_mod.backup_dir(cfg)
        for path, created, size in backup_mod.list_backups(directory):
            ctx.out(_t("{isoformat}  {size:>10} Bytes  {name}", isoformat=created.isoformat(sep=' ', timespec='seconds'), size=size, name=path.name))
        return 0

    if args.backup_cmd == "restore":
        if not args.yes and not _confirm(ctx):
            return 1
        try:
            restored = backup_mod.restore_backup(args.archive, dry_run=args.dry_run,
                                                  running_check=RUNNING_CHECK)
        except ValueError as exc:
            ctx.err(_t("Fehler: {exc}", exc=exc))
            return 1
        for line in restored:
            ctx.out(line)
        return 0

    raise ValueError(_t("Unbekannter Unterbefehl '{backup_cmd}'", backup_cmd=args.backup_cmd))
