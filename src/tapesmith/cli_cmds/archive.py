"""`p12 archive`: Verlaufseinträge nachträglich ins Git-Archiv legen und Secret-Scan
(auch für Pre-Commit-Hooks im Infra-Repo)."""

import argparse
from pathlib import Path

from tapesmith import paths
from tapesmith.archive import GitRunner, archive_entry, git_commit, scan_path
from tapesmith.cli_cmds.base import CliContext
from tapesmith.history import HistoryStore
from tapesmith.i18n import N_, _t

COMMAND = "archive"
HELP = N_("Druckarchiv verwalten (Git-Archiv, Secret-Scan)")

# Für Tests: eigenen Git-Runner einsetzen, ohne echtes Git aufzurufen.
GIT_RUNNER: GitRunner | None = None


def register(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="archive_cmd", required=True)

    add_p = sub.add_parser("add", help=_t("einen Verlaufseintrag nachträglich archivieren"))
    add_p.add_argument("target", help=_t("'last' oder die ID aus 'p12 history'"))
    add_p.add_argument("--dir", type=Path, metavar=_t("ORDNER"), help=_t("Archivordner (sonst archive.dir)"))

    scan_p = sub.add_parser("scan", help=_t("Secret-Scan über eine Datei oder einen Ordner"))
    scan_p.add_argument("path", type=Path)


def _resolve_entry(store: HistoryStore, target: str):
    if target == "last":
        entry = store.last()
        if entry is None:
            raise ValueError(_t("Verlauf ist leer"))
        return entry
    try:
        entry_id = int(target)
    except ValueError as exc:
        raise ValueError(_t("Ungültige Verlaufs-ID '{target}'", target=target)) from exc
    return store.get(entry_id)


def _run_add(args: argparse.Namespace, ctx: CliContext) -> int:
    cfg = ctx.load_config()
    directory = args.dir or (cfg.get("archive") or {}).get("dir")
    if not directory:
        raise ValueError(_t("archive.dir nicht gesetzt"))
    directory = Path(directory)

    with HistoryStore(paths.history_db_path()) as store:
        entry = _resolve_entry(store, args.target)
        head = store.head_image(entry.id)

    profile = ctx.load_profile()
    files = archive_entry(entry, head, directory, profile)
    for path in files:
        ctx.out(_t("Archiviert: {path}", path=path))

    if bool((cfg.get("archive") or {}).get("git_commit", False)):
        message = f"Label #{entry.id}: {entry.title}"
        result = git_commit(files, directory, message, runner=GIT_RUNNER)
        if result is not None:
            ctx.err(result)
        else:
            ctx.out("committet")
    return 0


def _run_scan(args: argparse.Namespace, ctx: CliContext) -> int:
    findings = scan_path(args.path)
    if not findings:
        ctx.out(_t("keine Secrets gefunden"))
        return 0
    for path, finding in findings:
        ctx.out(f"{path}: {finding.kind} ({finding.excerpt})")
    return 1


def run(args: argparse.Namespace, ctx: CliContext) -> int:
    if args.archive_cmd == "add":
        return _run_add(args, ctx)
    if args.archive_cmd == "scan":
        return _run_scan(args, ctx)
    raise ValueError(_t("Unbekannter Unterbefehl 'archive {archive_cmd}'", archive_cmd=args.archive_cmd))
