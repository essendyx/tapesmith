"""Plugin-Befehl `uninstall`: installierte App entfernen, Benutzerdaten bleiben.

Gleichbedeutend mit `python -m tapesmith uninstall` (siehe `tapesmith.install.uninstaller`)."""

from __future__ import annotations

import argparse

from tapesmith.i18n import N_, _t

COMMAND = "uninstall"
HELP = N_("Tapesmith deinstallieren (Benutzerdaten bleiben erhalten)")


def register(parser: argparse.ArgumentParser) -> None:
    parser.description = _t(HELP)
    parser.add_argument("--root", default=None)
    parser.add_argument("--no-shortcuts", action="store_true")
    parser.add_argument("--no-registry", action="store_true")
    parser.add_argument("--quiet", action="store_true")


def run(args: argparse.Namespace, ctx) -> int:
    from tapesmith.install import uninstaller

    argv = []
    if args.root:
        argv += ["--root", str(args.root)]
    for flag in ("no_shortcuts", "no_registry", "quiet"):
        if getattr(args, flag):
            argv.append("--" + flag.replace("_", "-"))
    return uninstaller.main(argv)
