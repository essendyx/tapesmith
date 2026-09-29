"""Plugin-Befehl 'p12 app': Web-Oberfläche im Standardbrowser öffnen.

Ein eigenes lokales Fenster gibt es nicht mehr, die Oberfläche läuft nur im Browser. Startet den
Druckdienst bei Bedarf (`webui.browser.open_app`). `webui.browser` wird erst in `run()` geladen."""

import argparse
import importlib
from tapesmith.i18n import N_, _t

COMMAND = "app"
HELP = N_("Web-Oberfläche im Standardbrowser öffnen")


def register(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--route", default=None, metavar=_t("PFAD"), help=_t("Startseite, z. B. /verlauf"))
    parser.add_argument("--uri", default=None, help=_t("tapesmith://-URI vorausgefüllt öffnen"))
    parser.add_argument("--open", dest="open_action", default=None, metavar=_t("AKTION"))
    parser.add_argument("--path", default=None)
    # Früher: Browser statt App-Fenster. Heute immer Browser, bleibt für alte Skripte gültig.
    parser.add_argument("--browser", action="store_true", help=argparse.SUPPRESS)


def run(args: argparse.Namespace, ctx) -> int:
    browser = importlib.import_module("tapesmith.webui.browser")
    argv: list[str] = []
    if args.route is not None:
        argv += ["--route", args.route]
    if args.uri is not None:
        argv += ["--uri", args.uri]
    if args.open_action is not None:
        argv += ["--open", args.open_action]
    if args.path is not None:
        argv += ["--path", args.path]
    return browser.main(argv)
