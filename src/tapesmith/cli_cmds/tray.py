"""Plugin-Befehl 'p12 tray': Tray-App (Infobereich, globale Tastenkürzel) starten.

Ohne `--foreground` wird die Tray-App losgelöst gestartet und der Befehl kehrt sofort zurück;
eine bereits laufende Instanz beendet die neue sofort wieder (Einzelinstanz). PySide6 wird erst
bei `--foreground` geladen.
"""

import argparse
import importlib

from tapesmith import launch
from tapesmith.i18n import N_, _t

COMMAND = "tray"
HELP = N_("Tray-App (Infobereich, Schnelldruck per Tastenkürzel) starten")

SPAWN = launch.spawn_detached


def register(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--foreground", action="store_true",
                        help=_t("im aktuellen Prozess laufen lassen statt losgelöst zu starten"))
    parser.add_argument("--no-hotkeys", action="store_true", help=_t("keine globalen Tastenkürzel registrieren"))


def run(args, ctx) -> int:
    flags = ["--no-hotkeys"] if args.no_hotkeys else []
    if args.foreground:
        try:
            tray = importlib.import_module("tapesmith.gui.tray")
        except ImportError as exc:
            raise ValueError(_t("PySide6 fehlt, mit 'pip install PySide6' nachinstallieren")) from exc
        return tray.main(flags)
    try:
        SPAWN(launch.app_argv("tray", *flags))
    except RuntimeError as exc:
        raise ValueError(_t("Tray-App nicht gestartet: {exc}", exc=exc)) from exc
    ctx.out(_t("Tray-App gestartet"))
    return 0
