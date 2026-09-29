"""`tapesmith module`: Module anzeigen, ein- und ausschalten (config.json `modules.enabled`).

`list` zeigt jedes Modul mit Zustand, Name und Erklärsatz (`--json` maschinenlesbar),
`enable`/`disable` schalten eines oder mehrere Module (`--all`: alle). Die Oberfläche übernimmt die
Änderung ohne Neustart."""

from __future__ import annotations

import argparse
import json

from tapesmith import modules
from tapesmith.cli_cmds.base import CliContext
from tapesmith.errors import EXIT_ERROR, EXIT_OK
from tapesmith.i18n import N_, _t

COMMAND = "module"
HELP = N_("Module anzeigen, ein- und ausschalten (Inventar, Datenträger, Homelab-Integrationen)")


def register(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="module_cmd", required=True)
    ls = sub.add_parser("list", help=_t("alle Module mit Zustand"))
    ls.add_argument("--json", action="store_true", help=_t("als JSON ausgeben"))
    for name, text in (("enable", _t("Module einschalten")), ("disable", _t("Module ausschalten"))):
        p = sub.add_parser(name, help=text)
        p.add_argument("ids", nargs="*", metavar=_t("MODUL"), help=", ".join(modules.MODULE_IDS))
        p.add_argument("--all", action="store_true", help=_t("alle Module"))


def _names(ids) -> str:
    return ", ".join(modules.texts(module_id)["name"] for module_id in ids)


def _list(args, ctx: CliContext) -> int:
    enabled = set(modules.enabled_ids(ctx.load_config()))
    if args.json:
        data = [{"id": item.id, "enabled": item.id in enabled, **modules.texts(item.id)}
                for item in modules.REGISTRY]
        ctx.out(json.dumps(data, ensure_ascii=False, indent=2))
        return EXIT_OK
    for item in modules.REGISTRY:
        texts = modules.texts(item.id)
        mark = "[x]" if item.id in enabled else "[ ]"
        ctx.out(f"{mark} {item.id:14} {texts['name']}")
        ctx.out(f"    {texts['description']}")
    ctx.out("")
    ctx.out(_t("Einschalten: tapesmith module enable <modul>, ausschalten: tapesmith module disable <modul>"))
    return EXIT_OK


def _switch(args, ctx: CliContext, enabled: bool) -> int:
    ids = list(modules.MODULE_IDS) if args.all else list(dict.fromkeys(args.ids))
    if not ids:
        ctx.err(_t("Fehler: Modul angeben oder --all (bekannt: ") + ", ".join(modules.MODULE_IDS) + ")")
        return EXIT_ERROR
    for module_id in ids:
        try:
            modules.spec(module_id)
        except modules.UnknownModule as exc:
            ctx.err(_t("Fehler: {exc}", exc=exc))
            return EXIT_ERROR
    for module_id in ids:
        modules.set_enabled(module_id, enabled)
    ctx.out(f"{'eingeschaltet' if enabled else 'ausgeschaltet'}: {_names(ids)}")
    return EXIT_OK


def run(args: argparse.Namespace, ctx: CliContext) -> int:
    if args.module_cmd == "list":
        return _list(args, ctx)
    return _switch(args, ctx, args.module_cmd == "enable")
