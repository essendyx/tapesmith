"""Plugin-Befehl 'p12 kabel': NetBox-CSV-Import, TIA-606-ID-Schema und Kabel-Register.

Zeigt standardmäßig nur die Tabelle bzw. die erzeugten IDs (nie ein automatischer Druck); ein
echter Seriendruck läuft nur über `--dry-run`/`--preview`/`--contact-sheet` (Zusammenfassung bzw.
Kontaktabzug, nie ein echter Druck ohne diese Optionen in Tests) oder `ids --print` zusammen mit
den Optionen aus `add_series_options`.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from tapesmith import numbering
from tapesmith.cli_cmds.base import CliContext
from tapesmith.dataimport.mapping import MappingStore
from tapesmith.errors import EXIT_ERROR, EXIT_OK
from tapesmith.integrations import netbox, settings, tia606
from tapesmith.integrations.cliprint import add_series_options, print_rows, run_guarded
from tapesmith.i18n import N_, _t

COMMAND = "kabel"
HELP = N_("NetBox-CSV-Import und TIA-606-ID-Schema für Kabel-Labels")


def register(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="kabel_cmd", required=True)

    p_netbox = sub.add_parser("netbox", help=_t("NetBox-Kabelexport (CSV) einlesen"))
    p_netbox.add_argument("csv", type=Path, help=_t("CSV-Datei aus dem NetBox-Kabelexport"))
    p_netbox.add_argument("--map", action="append", default=[], metavar=_t("FELD=SPALTE"),
                          help=_t("Spaltenzuordnung überschreiben, z. B. quelle=Side A"))
    p_netbox.add_argument("--neue-ids", action="store_true",
                          help=_t("fehlende Kabel-IDs aus dem Nummernkreis 'kabel' vergeben"))
    p_netbox.add_argument("--speichern", action="store_true", help=_t("Spaltenzuordnung merken"))
    p_netbox.add_argument("--register", action="store_true", help=_t("Zeilen ins Kabel-Register eintragen"))
    add_series_options(p_netbox, template="kabelfahne")

    p_ids = sub.add_parser("ids", help=_t("TIA-606-Port-IDs erzeugen oder freie IDs reservieren"))
    p_ids.add_argument("--schema", metavar="RACK", help=_t("Rack-Bezeichnung (Schema-Modus)"))
    p_ids.add_argument("--units", metavar="1-24", help=_t("Höheneinheiten (Schema-Modus)"))
    p_ids.add_argument("--ports", metavar="1-24", help=_t("Ports (Schema-Modus)"))
    p_ids.add_argument("--muster", metavar=_t("MUSTER"), help=_t("Muster (Standard: kabel.tia_pattern)"))
    p_ids.add_argument("--frei", type=int, metavar="N", help=_t("N freie fortlaufende IDs reservieren"))
    p_ids.add_argument("--register", action="store_true", help=_t("erzeugte IDs ins Register eintragen"))
    p_ids.add_argument("--print", action="store_true", dest="do_print", help=_t("erzeugte IDs als Serie drucken"))
    add_series_options(p_ids, template="kabelfahne")

    p_reg = sub.add_parser("register", help=_t("Kabel-Register anzeigen"))
    p_reg.add_argument("--suche", default="", metavar="TEXT", help=_t("Suchtext"))

    p_check = sub.add_parser("pruefen", help=_t("Kabel-IDs auf Vergabe prüfen (Exit 1, wenn eine vergeben ist)"))
    p_check.add_argument("id", nargs="+", metavar="ID", help=_t("zu prüfende Kabel-IDs"))


def _parse_map(items: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for item in items:
        key, sep, col = item.partition("=")
        if not sep or not key.strip():
            raise ValueError(_t("--map erwartet feld=spalte, nicht '{item}'", item=item))
        mapping[key.strip()] = col.strip()
    return mapping


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _run_netbox(args: argparse.Namespace, homelab: dict, ctx: CliContext) -> int:
    data = args.csv.read_bytes()
    table = netbox.read_export(data, source=args.csv.name)
    store = MappingStore()
    mapping: dict[str, str | list[str]] = dict(netbox.suggest_mapping(table, store))
    mapping.update(_parse_map(args.map))

    register = tia606.KabelRegister()
    dry_run = getattr(args, "dry_run", False)
    ranges = numbering.NumberRanges()

    def new_id(n: int) -> list[str]:
        if dry_run:
            return [f"neu {i + 1}" for i in range(n)]
        return tia606.free_ids(ranges, homelab, n)

    result = netbox.build_rows(table, mapping, register=register,
                               new_id=new_id if args.neue_ids else None)

    if args.speichern:
        netbox.save_mapping(store, table, mapping)

    for row in result.rows:
        marker = _t(" (neu)") if row.neu else ""
        ctx.out(f"{row.kabel_id}\t{row.quelle}\t{row.ziel}\t{row.kabeltyp}{marker}")
    for warning in result.warnings:
        ctx.err(_t("Hinweis: {warning}", warning=warning))
    if result.duplicates:
        ctx.err(_t("Duplikate: {items}", items=', '.join(result.duplicates)))

    if args.register:
        if dry_run:
            ctx.err(_t("Hinweis: --dry-run: Register nicht geändert"))
        elif result.duplicates:
            ctx.err(_t("Register nicht geändert (Duplikate)"))
            return EXIT_ERROR
        else:
            entries = [
                tia606.KabelEntry(id=r.kabel_id, quelle=r.quelle, ziel=r.ziel, kabeltyp=r.kabeltyp,
                                  quelle_import="netbox", created=_now())
                for r in result.rows if r.kabel_id
            ]
            register.add(entries, allow_existing=True)

    wants_preview = bool(dry_run or getattr(args, "preview", None) or getattr(args, "contact_sheet", None))
    if wants_preview:
        rows = [{"kabel_id": r.kabel_id, "quelle": r.quelle, "ziel": r.ziel, "kabeltyp": r.kabeltyp}
               for r in result.rows]
        return print_rows(ctx, args, args.template, rows)
    return EXIT_OK


def _run_ids(args: argparse.Namespace, homelab: dict, ctx: CliContext) -> int:
    dry_run = getattr(args, "dry_run", False)
    register = tia606.KabelRegister()

    if args.schema:
        pattern = args.muster or settings.setting(homelab, "kabel.tia_pattern")
        units = tia606.parse_numbers(args.units or "")
        ports = tia606.parse_numbers(args.ports or "")
        port_range = tia606.PortRange(rack=args.schema, units=units, ports=ports)
        ids = tia606.generate(pattern, [port_range])
        quelle_import = "schema"
    elif args.frei:
        if dry_run:
            ids = [f"neu {i + 1}" for i in range(args.frei)]
        else:
            ranges = numbering.NumberRanges()
            ids = tia606.free_ids(ranges, homelab, args.frei)
        quelle_import = "frei"
    else:
        ctx.err(_t("Bitte --schema oder --frei angeben"))
        return EXIT_ERROR

    duplicates = register.duplicates(ids)
    if duplicates:
        ctx.err(_t("Bereits vergeben: {items}", items=', '.join(duplicates)))

    if args.register:
        if dry_run:
            ctx.err(_t("Hinweis: --dry-run: Register nicht geändert"))
        elif duplicates:
            ctx.err(_t("Register nicht geändert (Duplikate)"))
            return EXIT_ERROR
        else:
            entries = [tia606.KabelEntry(id=i, quelle="", ziel="", kabeltyp="", quelle_import=quelle_import,
                                         created=_now()) for i in ids]
            register.add(entries)

    for kabel_id in ids:
        ctx.out(kabel_id)

    if getattr(args, "do_print", False):
        rows = [{"kabel_id": i} for i in ids]
        return print_rows(ctx, args, args.template, rows)
    return EXIT_OK


def _run_register(args: argparse.Namespace, ctx: CliContext) -> int:
    register = tia606.KabelRegister()
    entries = register.all()
    if args.suche:
        needle = args.suche.casefold()
        entries = [e for e in entries
                  if needle in e.id.casefold() or needle in e.quelle.casefold() or needle in e.ziel.casefold()]
    if not entries:
        ctx.out(_t("Keine Einträge"))
        return EXIT_OK
    for e in entries:
        ctx.out(f"{e.id}\t{e.quelle}\t{e.ziel}\t{e.kabeltyp}\t{e.quelle_import}\t{e.created}")
    return EXIT_OK


def _run_check(args: argparse.Namespace, ctx: CliContext) -> int:
    register = tia606.KabelRegister()
    any_used = False
    for kabel_id in args.id:
        used = register.exists(kabel_id)
        ctx.out(f"{kabel_id}: {'vergeben' if used else 'frei'}")
        any_used = any_used or used
    return EXIT_ERROR if any_used else EXIT_OK


def _dispatch(args: argparse.Namespace, ctx: CliContext) -> int:
    homelab = settings.load_settings()
    if args.kabel_cmd == "netbox":
        return _run_netbox(args, homelab, ctx)
    if args.kabel_cmd == "ids":
        return _run_ids(args, homelab, ctx)
    if args.kabel_cmd == "register":
        return _run_register(args, ctx)
    if args.kabel_cmd == "pruefen":
        return _run_check(args, ctx)
    raise ValueError(_t("Unbekannter Unterbefehl 'kabel {kabel_cmd}'", kabel_cmd=args.kabel_cmd))


def run(args: argparse.Namespace, ctx: CliContext) -> int:
    return run_guarded(ctx, lambda: _dispatch(args, ctx))
