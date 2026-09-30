"""`tapesmith drives`: Wechseldatenträger anzeigen und ein Kurzetikett vorschlagen/drucken."""

import argparse
import json

from tapesmith.cli_cmds.base import CliContext, add_print_options
from tapesmith.document.render import render_spec
from tapesmith.drives import DriveInfo, WinDrivesBackend, list_drives, suggest_label
from tapesmith.jobs import JobMeta
from tapesmith.render.compose import LabelSpec
from tapesmith.tape.profiles import current_tape
from tapesmith.i18n import N_, _t

COMMAND = "drives"
HELP = N_("Wechseldatenträger anzeigen und Kurzetikett drucken")

BACKEND_FACTORY = WinDrivesBackend


def register(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help=_t("Ausgabe als JSON"))
    sub = parser.add_subparsers(dest="drives_cmd")

    p_label = sub.add_parser("label", help=_t("Kurzetikett für ein Laufwerk rendern/drucken"))
    p_label.add_argument("root", help=_t("Laufwerksbuchstabe, z. B. E:"))
    add_print_options(p_label)


def _find_drive(drives: list[DriveInfo], root: str) -> DriveInfo:
    normalized = root.rstrip("\\").upper()
    if not normalized.endswith(":"):
        normalized += ":"
    normalized += "\\"
    for drive in drives:
        if drive.root.upper() == normalized:
            return drive
    available = ", ".join(d.root for d in drives) or "keine"
    raise ValueError(_t("Laufwerk {root} nicht gefunden (vorhanden: {available})", root=root, available=available))


def _format_row(drive: DriveInfo) -> str:
    line1, line2 = suggest_label(drive)
    return f"{drive.root}  {line1}  {line2}  {drive.bus}"


def run(args: argparse.Namespace, ctx: CliContext) -> int:
    drives = list_drives(BACKEND_FACTORY())

    if getattr(args, "drives_cmd", None) == "label":
        drive = _find_drive(drives, args.root)
        lines = suggest_label(drive)
        profile = ctx.load_profile()
        tape = current_tape(ctx.load_config())
        spec = LabelSpec(lines=lines)
        result = render_spec(spec, profile, tape)
        meta = JobMeta(source="cli", kind="text", title=" ".join(lines))
        ctx.emit_label(result, meta)
        return 0

    if args.json:
        ctx.out(json.dumps([
            {"root": d.root, "label": d.label, "size_bytes": d.size_bytes, "free_bytes": d.free_bytes,
             "filesystem": d.filesystem, "bus": d.bus, "removable": d.removable}
            for d in drives
        ], ensure_ascii=False, indent=2))
        return 0

    if not drives:
        ctx.out(_t("Kein Wechseldatenträger gefunden"))
        return 0
    for drive in drives:
        ctx.out(_format_row(drive))
    return 0
