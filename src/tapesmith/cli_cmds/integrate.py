"""Plugin-Befehl 'tapesmith integrate': Explorer-Kontextmenü, URI-Schema, Autostart.

`tapesmith integrate install` schreibt in die echte Registry (HKCU). Das führt der Benutzer selbst
aus; automatisierte Abläufe und Tests nutzen höchstens `status` oder
`--dry-run`."""

import argparse
import json

from tapesmith.integration import PARTS, WinRegBackend, install, status as integration_status, uninstall
from tapesmith.i18n import N_, _t

COMMAND = "integrate"
HELP = N_("Windows-Integration: Kontextmenü, URI-Schema, Autostart einrichten/entfernen")

# Tests ersetzen dieses Modulattribut durch eine FakeRegistry-Fabrik.
BACKEND_FACTORY = WinRegBackend


def _add_part_flags(parser: argparse.ArgumentParser) -> None:
    for part in PARTS:
        parser.add_argument(f"--{part}", action="store_true", help=_t("nur Teil '{part}'", part=part))
    parser.add_argument("--dry-run", action="store_true", help=_t("nur anzeigen, nichts schreiben"))


def _selected_parts(args: argparse.Namespace) -> tuple[str, ...]:
    return tuple(part for part in PARTS if getattr(args, part, False))


def register(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="integrate_cmd", required=True)
    _add_part_flags(sub.add_parser("install", help=_t("Kontextmenü/URI-Schema/Autostart einrichten (ohne Admin)")))
    _add_part_flags(sub.add_parser("uninstall", help=_t("Kontextmenü/URI-Schema/Autostart entfernen")))
    s = sub.add_parser("status", help=_t("Installationsstatus anzeigen"))
    s.add_argument("--json", action="store_true", help=_t("als JSON ausgeben"))


def run(args: argparse.Namespace, ctx) -> int:
    backend = BACKEND_FACTORY()

    if args.integrate_cmd == "install":
        parts = _selected_parts(args) or ("context", "uri")
        lines = install(backend, parts, dry_run=args.dry_run)
        if lines:
            for line in lines:
                ctx.out(line)
            if "context" in parts:
                ctx.out(_t('Kontextmenü: unter Windows 11 unter "Weitere Optionen anzeigen" (Umschalt+F10)'))
        else:
            ctx.out(_t("Nichts zu tun, bereits installiert"))
        return 0

    if args.integrate_cmd == "uninstall":
        parts = _selected_parts(args) or PARTS
        lines = uninstall(backend, parts, dry_run=args.dry_run)
        if lines:
            for line in lines:
                ctx.out(line)
        else:
            ctx.out(_t("Nichts zu tun, nicht installiert"))
        return 0

    # args.integrate_cmd == "status"
    result = integration_status(backend)
    if args.json:
        ctx.out(json.dumps(result, ensure_ascii=False))
    else:
        for part, state in result.items():
            ctx.out(f"{part}: {state}")
    return 0
