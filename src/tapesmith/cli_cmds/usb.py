"""Plugin-Befehl 'p12 usb': USB-Diagnose (experimentell), P12 am USB erkennen."""

import argparse
import json

from tapesmith.transport.usb import diagnose_usb, find_usb_devices, list_usbprint_paths
from tapesmith.i18n import N_, _t

COMMAND = "usb"
HELP = N_("USB-Diagnose (experimentell): P12 am USB erkennen")

# Modulattribute statt Default-Argumente, damit Tests Registry/SetupAPI faken können; None -> die
# echten, nur lesenden Funktionen.
READER = None
ENUMERATOR = None


def register(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help=_t("Ausgabe als JSON"))


def run(args: argparse.Namespace, ctx) -> int:
    lines = diagnose_usb(find_usb_devices(READER))
    paths = list_usbprint_paths(ENUMERATOR)
    if args.json:
        ctx.out(json.dumps({"lines": lines, "usbprint_paths": paths}, ensure_ascii=False))
        return 0
    for line in lines:
        ctx.out(line)
    for p in paths:
        ctx.out(f"usbprint: {p}")
    return 0
