"""Plugin-Befehl 'p12 disks': Seriennummern eines Homelab-Hosts per SSH einlesen und als
Serie über die Vorlage `datentraeger` drucken, als Ergänzung zu `p12 batch`.

Kein echter SSH-Aufruf standardmäßig: `RUNNER` ist injizierbar (Tests ersetzen es), Default ist
`sshscan.default_runner` (über `scan_host`). Vorlagen-Zähler kommen aus dem zentralen
Nummernkreis-Ordner (`numbering.counter_store(cfg)`), nie aus `CounterStore(paths.app_dir()/…)`.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
from datetime import datetime
from pathlib import Path

from tapesmith import numbering
from tapesmith.cli_cmds.base import CliContext, add_print_options, emit_labels, parse_sets
from tapesmith.dataimport.batch import batch_meta, build_batch, commit_counters, contact_sheet
from tapesmith.errors import EXIT_ERROR, EXIT_OK, EXIT_UNREACHABLE
from tapesmith.integrations import scancache
from tapesmith.sshscan import DiskRow, Runner, SshError, find_host, hosts_from_config, rows_for_template, scan_host
from tapesmith.tape.profiles import current_tape
from tapesmith.templates.store import find_template
from tapesmith.i18n import N_, _t

COMMAND = "disks"
HELP = N_("Datenträger eines Hosts per SSH scannen und als Serie drucken")

# Für Tests: eigenen Runner einsetzen, ohne echtes ssh.exe aufzurufen.
RUNNER: Runner | None = None

log = logging.getLogger(__name__)


def register(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="disks_cmd", required=True)

    sub.add_parser("hosts", help=_t("konfigurierte SSH-Hosts auflisten"))

    p_scan = sub.add_parser("scan", help=_t("Platten eines Hosts auflisten"))
    p_scan.add_argument("host", help=_t("Name aus ssh.hosts"))
    p_scan.add_argument("--json", action="store_true", help=_t("Ausgabe als JSON"))

    p_print = sub.add_parser("print", help=_t("Platten eines Hosts als Serie drucken"))
    p_print.add_argument("host", help=_t("Name aus ssh.hosts"))
    p_print.add_argument("--device", metavar="sda,sdb", help=_t("nur diese Geräte (Komma-getrennt)"))
    p_print.add_argument("--slot", action="append", default=[], metavar=_t("GERÄT=SLOT"),
                         help=_t("Slot-Text je Gerät, z. B. sda=SSD-1"))
    p_print.add_argument("--template", default="datentraeger", metavar=_t("NAME|PFAD"))
    p_print.add_argument("--dry-run", action="store_true",
                         help=_t("nur Zusammenfassung/Kontaktabzug, nicht drucken, keine Zähler"))
    p_print.add_argument("--contact-sheet", type=Path, metavar=_t("DATEI.png"), help=_t("Kontaktabzug schreiben"))
    add_print_options(p_print)


def _scan(host, cfg: dict) -> list[DiskRow]:
    ssh_cfg = cfg.get("ssh") or {}
    timeout_s = ssh_cfg.get("timeout_s", 20)
    strict_host_key = ssh_cfg.get("strict_host_key", True)
    disks = scan_host(host, runner=RUNNER, timeout_s=timeout_s, strict_host_key=strict_host_key)
    try:
        scancache.save_scan(host.name, disks, when=datetime.now())
    except (OSError, ValueError) as exc:
        log.warning("Scan-Cache für %s nicht gespeichert: %s", host.name, exc)
    return disks


def _pool_text(disk: DiskRow) -> str:
    if not disk.pool:
        return ""
    return f"{disk.pool}/{disk.vdev}" if disk.vdev else disk.pool


def _run_hosts(cfg: dict, ctx: CliContext) -> int:
    hosts = hosts_from_config(cfg)
    if not hosts:
        ctx.out(_t("Keine Hosts in ssh.hosts, bitte in config.json eintragen (Name, Host, Benutzer, Schlüsselpfad)"))
        return EXIT_OK
    for host in hosts:
        ctx.out(f"{host.name}  {host.user}@{host.host}:{host.port}  {host.key}")
    return EXIT_OK


def _run_scan(args: argparse.Namespace, cfg: dict, ctx: CliContext) -> int:
    host = find_host(cfg, args.host)
    disks = _scan(host, cfg)
    if args.json:
        ctx.out(json.dumps([dataclasses.asdict(d) for d in disks], ensure_ascii=False, indent=2))
        return EXIT_OK
    if not disks:
        ctx.out(_t("Keine Platten gefunden"))
        return EXIT_OK
    for disk in disks:
        ctx.out(f"{disk.device}  {disk.model}  {disk.serial}  {disk.by_id or ''}  "
                f"{_pool_text(disk)}  {disk.size}")
    return EXIT_OK


def _select_devices(disks: list[DiskRow], device_arg: str | None, ctx: CliContext) -> list[DiskRow] | None:
    if not device_arg:
        return disks
    wanted = [d.strip() for d in device_arg.split(",") if d.strip()]
    known = {d.device for d in disks}
    unknown = [d for d in wanted if d not in known]
    if unknown:
        ctx.err(_t("Unbekannte Geräte: {items} (vorhanden: {items2})", items=', '.join(unknown), items2=', '.join(sorted(known))))
        return None
    return [d for d in disks if d.device in wanted]


def _run_print(args: argparse.Namespace, cfg: dict, ctx: CliContext) -> int:
    host = find_host(cfg, args.host)
    disks = _scan(host, cfg)

    selected = _select_devices(disks, args.device, ctx)
    if selected is None:
        return EXIT_ERROR

    slots = parse_sets(args.slot) if args.slot else {}
    rows = rows_for_template(selected, slots)

    template = find_template(args.template)
    profile = ctx.load_profile()
    tape = current_tape(cfg)
    counters = numbering.counter_store(cfg)

    try:
        plan = build_batch(template, rows, profile, now=datetime.now(), counters=counters, tape=tape)
    except ValueError as exc:
        ctx.err(str(exc))
        return EXIT_ERROR

    for error in plan.errors:
        ctx.err(error)

    if args.contact_sheet:
        contact_sheet(plan, profile, tape=tape).save(args.contact_sheet)
        ctx.out(_t("Kontaktabzug: {contact_sheet}", contact_sheet=args.contact_sheet))

    cut_marks = not getattr(args, "no_cut_marks", False)
    if args.dry_run:
        ctx.out(plan.summary(profile, chain=args.chain, cut_marks=cut_marks))
        return EXIT_OK

    if not plan.labels:
        ctx.err(_t("Keine druckbaren Zeilen"))
        return EXIT_ERROR

    meta = batch_meta(plan, "cli")
    printed = emit_labels(ctx, plan.labels, meta)
    if printed:
        commit_counters(plan, counters)
    return EXIT_OK


def run(args: argparse.Namespace, ctx: CliContext) -> int:
    cfg = ctx.load_config()
    try:
        if args.disks_cmd == "hosts":
            return _run_hosts(cfg, ctx)
        if args.disks_cmd == "scan":
            return _run_scan(args, cfg, ctx)
        if args.disks_cmd == "print":
            return _run_print(args, cfg, ctx)
    except SshError as exc:
        ctx.err(str(exc))
        return EXIT_UNREACHABLE
    raise ValueError(_t("Unbekannter Unterbefehl 'disks {disks_cmd}'", disks_cmd=args.disks_cmd))
