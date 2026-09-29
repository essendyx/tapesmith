"""Plugin-Befehl 'p12 gui': heißt jetzt 'p12 app' und öffnet wie dieser die Web-Oberfläche im
Standardbrowser.

`--selftest`/`--selftest-out` rufen den Qt-freien Selbsttest (`tapesmith.selftest`). Browser- und
Selbsttest-Modul werden erst in `run()` importiert: `discover_commands()` lädt jedes Plugin bei
jedem CLI-Aufruf, reine Kommandozeilenbefehle sollen kein Qt laden.
"""

import argparse
import importlib
import sys
from pathlib import Path
from tapesmith.i18n import N_, _t

COMMAND = "gui"
HELP = N_("Web-Oberfläche im Browser öffnen (wie 'p12 app') oder Selbsttest")
RENAMED_HINT = N_("Hinweis: ‚p12 gui‘ heißt jetzt ‚p12 app‘.")


def register(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--route", default=None, metavar=_t("PFAD"), help=_t("Startseite, z. B. /verlauf"))
    parser.add_argument("--selftest", action="store_true", help=_t("Selbsttest ausführen (druckt nie)"))
    parser.add_argument("--selftest-out", type=Path, metavar=_t("PFAD"),
                        help=_t("Selbsttest-Ausgabe in diese Datei schreiben"))


def run(args, ctx) -> int:
    if args.selftest or args.selftest_out is not None:
        selftest = importlib.import_module("tapesmith.selftest")
        argv: list[str] = []
        if args.selftest_out is not None:
            argv += ["--selftest-out", str(args.selftest_out)]
        return selftest.main(argv)
    print(_t(RENAMED_HINT), file=sys.stderr)
    browser = importlib.import_module("tapesmith.webui.browser")
    return browser.main(["--route", args.route] if args.route is not None else [])
