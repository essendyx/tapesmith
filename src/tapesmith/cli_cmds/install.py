"""Plugin-Befehl `install`: Tapesmith installieren bzw. mit `--status` den Zustand zeigen.

`python -m tapesmith install` legt unter `%LOCALAPPDATA%\\Programs\\Tapesmith` eine eigene
Python-Umgebung je Version an (siehe `tapesmith.install.installer`). `install --status` (bzw. das
ältere `install status`) liest nur. Deinstallation: `python -m tapesmith uninstall`."""

from __future__ import annotations

import argparse
import json

from tapesmith.install import installer
from tapesmith.install.registry import UninstallRegistry
from tapesmith.install.shortcuts import start_menu_dir
from tapesmith.i18n import N_, _t

COMMAND = "install"
HELP = N_("Tapesmith installieren (eigene Python-Umgebung, ohne Adminrechte) bzw. Zustand anzeigen")

# Tests ersetzen dieses Modulattribut durch eine Fake-Fabrik (FakeUninstallRegistry).
BACKEND_FACTORY = UninstallRegistry


def register(parser: argparse.ArgumentParser) -> None:
    parser.description = _t(HELP)
    parser.add_argument("action", nargs="?", choices=["status"], help=_t("wie --status"))
    installer.add_arguments(parser)


def status_dict() -> dict:
    data = installer.status_dict()
    if not data.get("installed"):
        return data
    try:
        menu_exists = start_menu_dir().exists()
    except RuntimeError:
        menu_exists = None
    data["start_menu"] = menu_exists
    data["uninstall_entry"] = BACKEND_FACTORY().get("DisplayName") is not None
    return data


def run(args: argparse.Namespace, ctx) -> int:
    if args.action == "status" or args.status:
        data = status_dict()
        if args.json:
            ctx.out(json.dumps(data, ensure_ascii=False))
            return 0
        for line in installer.status_text(data):
            ctx.out(line)
        if data.get("installed"):
            ctx.out(_t("Startmenü: {value}", value=_t("vorhanden") if data["start_menu"] else _t("fehlt")))
            ctx.out(_t("Installierte Apps: {value}", value=_t("vorhanden") if data["uninstall_entry"] else _t("fehlt")))
        return 0
    return installer.run_args(args)
