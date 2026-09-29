"""Plugin-Befehl 'p12 install': Installationszustand anzeigen (nur lesend).

Installation und Deinstallation laufen über die EXE selbst (`Tapesmith.exe --install` bzw.
`Installieren.cmd`), nicht über diese CLI."""

from __future__ import annotations

import argparse
import json

from tapesmith.install import junction, layout
from tapesmith.install.registry import UninstallRegistry
from tapesmith.install.shortcuts import start_menu_dir
from tapesmith.i18n import N_, _t

COMMAND = "install"
HELP = N_("Installationszustand anzeigen (nur lesend, keine Installation über die CLI)")
INSTALL_HINT = N_("Installation über Tapesmith.exe --install bzw. Installieren.cmd")

# Tests ersetzen dieses Modulattribut durch eine Fake-Fabrik (FakeUninstallRegistry).
BACKEND_FACTORY = UninstallRegistry


def register(parser: argparse.ArgumentParser) -> None:
    parser.description = f"{_t(HELP)} ({_t(INSTALL_HINT)})"
    sub = parser.add_subparsers(dest="install_cmd", required=True)
    status = sub.add_parser("status", help=_t("Wurzel, Version, Junction, Startmenü ({hint})", hint=_t(INSTALL_HINT)))
    status.add_argument("--json", action="store_true", help=_t("als JSON ausgeben"))


def status_dict() -> dict:
    try:
        root = layout.install_root()
    except RuntimeError as exc:
        return {"installed": False, "error": str(exc)}

    state = layout.read_state(root)
    if state is None:
        return {"installed": False, "root": str(root)}

    target = junction.read_junction(layout.current_link(root))
    try:
        menu_exists = start_menu_dir().exists()
    except RuntimeError:
        menu_exists = None

    reg = BACKEND_FACTORY()
    uninstall_entry = reg.get("DisplayName") is not None

    return {
        "installed": True,
        "root": str(root),
        "current": state.current,
        "previous": state.previous,
        "versions": list(state.versions),
        "failed": list(state.failed),
        "current_target": str(target) if target is not None else None,
        "start_menu": menu_exists,
        "uninstall_entry": uninstall_entry,
        "installed_at": state.installed_at,
        "channel": state.channel,
    }


def run(args: argparse.Namespace, ctx) -> int:
    data = status_dict()
    if args.json:
        ctx.out(json.dumps(data, ensure_ascii=False))
        return 0
    if not data.get("installed"):
        ctx.out(data.get("error") or _t("nicht installiert"))
        return 0
    ctx.out(_t("Wurzel: {root}", root=data['root']))
    ctx.out(_t("Aktiv: {current} (vorige: {value})", current=data['current'], value=data['previous'] or '-'))
    ctx.out(_t("Versionen: {value}", value=', '.join(data['versions']) or '-'))
    ctx.out(_t("Junction current: {value}", value=data['current_target'] or '-'))
    ctx.out(_t("Startmenü: {value}", value='vorhanden' if data['start_menu'] else 'fehlt'))
    ctx.out(_t("Installierte Apps: {value}", value='vorhanden' if data['uninstall_entry'] else 'fehlt'))
    return 0
