"""Plugin-Befehl 'tapesmith ble': BLE-Diagnose (experimentell), Geräte suchen."""

import argparse
import json

from tapesmith.transport.ble import DEFAULT_NAMES, EXPERIMENTAL_NOTE, BleakBackend, matches, scan_devices
from tapesmith.i18n import N_, _t

COMMAND = "ble"
HELP = N_("BLE-Diagnose (experimentell): Geräte suchen")

# Modulattribut statt Konstante, damit Tests ein Fake-Backend einsetzen können.
BACKEND_FACTORY = BleakBackend


def register(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="ble_cmd", required=True)
    s = sub.add_parser("scan", help=_t("nach BLE-Geräten suchen"))
    s.add_argument("--timeout", type=float, default=8.0, metavar="S", help=_t("Suchdauer in Sekunden"))
    s.add_argument("--json", action="store_true", help=_t("Ausgabe als JSON"))


def run(args: argparse.Namespace, ctx) -> int:
    ctx.err(_t(EXPERIMENTAL_NOTE))
    devices = scan_devices(args.timeout, backend=BACKEND_FACTORY())
    if args.json:
        ctx.out(json.dumps(
            [{"address": d.address, "name": d.name, "rssi": d.rssi} for d in devices],
            ensure_ascii=False))
        return 0
    if not devices:
        ctx.out(_t("Keine BLE-Geräte. Drucker an? Bei bestehender COM-Verbindung meldet sich der P12 evtl. nicht per BLE"))
        return 0
    for d in devices:
        marker = "P12" if matches(d, DEFAULT_NAMES, None) else ""
        rssi = d.rssi if d.rssi is not None else "-"
        ctx.out(f"{d.address}  {d.name or '-'}  RSSI {rssi}  {marker}")
    return 0
