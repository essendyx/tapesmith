"""Plugin-Befehl 'tapesmith config': Einstellungen anzeigen, lesen, setzen; Export/Import als Code."""

import argparse
import json
from pathlib import Path

from tapesmith import config, configcode, paths
from tapesmith.ipc.launcher import daemon_running
from tapesmith.i18n import N_, _t

COMMAND = "config"
HELP = N_("Konfiguration anzeigen, lesen, setzen, exportieren/importieren")


def register(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="config_cmd", required=True)

    s = sub.add_parser("show", help=_t("wirksame Werte aller Sektionen (inkl. Defaults)"))
    s.add_argument("--json", action="store_true")

    g = sub.add_parser("get", help=_t("einen Schlüssel lesen (z. B. queue.backoff_start_s)"))
    g.add_argument("key")

    st = sub.add_parser("set", help=_t("einen Schlüssel setzen"))
    st.add_argument("key")
    st.add_argument("value")

    sub.add_parser("path", help=_t("Pfad der config.json"))

    e = sub.add_parser("export", help=_t("Konfiguration als Code exportieren"))
    e.add_argument("dir", type=Path)
    e.add_argument("--no-templates", action="store_true")
    e.add_argument("--strip-secrets", action="store_true")

    i = sub.add_parser("import", help=_t("Konfiguration als Code importieren"))
    i.add_argument("dir", type=Path)
    i.add_argument("--dry-run", action="store_true")
    i.add_argument("--no-templates", action="store_true")


def _effective(cfg: dict) -> dict:
    """Alle Sektionen mit ihren wirksamen Werten (Konfiguration überschreibt Defaults)."""
    result = dict(cfg)
    for section, defaults in config.SECTION_DEFAULTS.items():
        result[section] = {**defaults, **cfg.get(section, {})}
    return result


def run(args: argparse.Namespace, ctx) -> int:
    if args.config_cmd == "show":
        cfg = _effective(ctx.load_config())
        if args.json:
            ctx.out(json.dumps(cfg, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            for key in sorted(cfg):
                ctx.out(f"{key}: {json.dumps(cfg[key], ensure_ascii=False)}")
        return 0

    if args.config_cmd == "get":
        cfg = ctx.load_config()
        try:
            value = config.setting(cfg, args.key)
        except KeyError:
            ctx.err(_t("Unbekannter Schlüssel '{key}'", key=args.key))
            return 1
        ctx.out(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False))
        return 0

    if args.config_cmd == "set":
        value = config.parse_cli_value(args.value)
        try:
            config.set_setting(args.key, value)
        except (config.UnknownSetting, KeyError, ValueError) as exc:
            ctx.err(_t("Fehler: {exc}", exc=exc))
            return 1
        ctx.out(f"{args.key} = {value!r}")
        if daemon_running():
            ctx.out(_t("Der Druckdienst übernimmt die Änderung vor dem nächsten Auftrag."))
        return 0

    if args.config_cmd == "path":
        ctx.out(str(paths.config_path()))
        return 0

    if args.config_cmd == "export":
        try:
            files = configcode.export_config(args.dir, include_templates=not args.no_templates,
                                              strip_secrets=args.strip_secrets)
        except ValueError as exc:
            ctx.err(_t("Fehler: {exc}", exc=exc))
            return 1
        ctx.out(_t("Exportiert nach {dir} ({count} Dateien)", dir=args.dir, count=len(files)))
        return 0

    if args.config_cmd == "import":
        try:
            plan = configcode.import_config(args.dir, dry_run=args.dry_run,
                                             include_templates=not args.no_templates)
        except ValueError as exc:
            ctx.err(_t("Fehler: {exc}", exc=exc))
            return 1
        for change in plan.changes:
            ctx.out(f"{change.kind}: {change.path}")
        for warning in plan.warnings:
            ctx.err(_t("Warnung: {warning}", warning=warning))
        if plan.backup_dir is not None:
            ctx.out(_t("Sicherung des alten Stands: {backup_dir}", backup_dir=plan.backup_dir))
        return 0

    raise ValueError(_t("Unbekannter Unterbefehl '{config_cmd}'", config_cmd=args.config_cmd))
