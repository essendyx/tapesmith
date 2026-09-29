"""Plugin-Befehl 'p12 platte': Assistent Platte tauschen (ZFS).

`status` zeigt defekte Geräte und Kandidaten, `plan` den `zpool replace`-Befehl samt Hinweisen und
Changelog-Entwurf (nur zum Kopieren, nichts wird ausgeführt), `label` druckt die Labels „defekt"
(alt) und „datentraeger" (neu). Kein echter SSH-Aufruf standardmäßig: `RUNNER` ist injizierbar
(Muster `cli_cmds/disks.py`).
"""

from __future__ import annotations

import argparse
import dataclasses
import json
from datetime import date, datetime
from pathlib import Path

from tapesmith.cli_cmds.base import CliContext, add_print_options
from tapesmith.errors import EXIT_ERROR, EXIT_OK
from tapesmith.integrations import zfsreplace
from tapesmith.integrations.cliprint import print_one, run_guarded
from tapesmith.sshscan import Runner, find_host
from tapesmith.i18n import N_, _t

COMMAND = "platte"
HELP = N_("Assistent Platte tauschen (ZFS): Probleme finden, Befehl planen, Labels drucken")

# Für Tests: eigenen Runner einsetzen, ohne echtes ssh.exe aufzurufen.
RUNNER: Runner | None = None


def register(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="platte_cmd", required=True)

    p_status = sub.add_parser("status", help=_t("defekte Geräte und Kandidaten eines Hosts"))
    p_status.add_argument("host", help=_t("Name aus ssh.hosts"))
    p_status.add_argument("--json", action="store_true", help=_t("Ausgabe als JSON"))

    p_plan = sub.add_parser("plan", help=_t("Ersatzbefehl, Hinweise und Changelog-Entwurf planen"))
    p_plan.add_argument("host", help=_t("Name aus ssh.hosts"))
    p_plan.add_argument("--alt", required=True, metavar="NAME", help=_t("Name des defekten Geräts"))
    p_plan.add_argument("--neu", required=True, metavar=_t("GERÄT"), help=_t("Gerät der neuen Platte, z. B. sdc"))
    p_plan.add_argument("--slot", required=True, help=_t("Slot-Text, z. B. SSD-1"))
    p_plan.add_argument("--grund", default="", help=_t("Grund (Standard: Zustand der alten Platte)"))
    p_plan.add_argument("--changelog", type=Path, metavar=_t("DATEI.md"),
                        help=_t("Changelog-Entwurf zusätzlich in eine Datei schreiben"))

    p_label = sub.add_parser("label", help=_t("Labels 'defekt' (alt) und 'datentraeger' (neu) drucken"))
    p_label.add_argument("host", help=_t("Name aus ssh.hosts"))
    p_label.add_argument("--alt", required=True, metavar="NAME", help=_t("Name des defekten Geräts"))
    p_label.add_argument("--neu", required=True, metavar=_t("GERÄT"), help=_t("Gerät der neuen Platte, z. B. sdc"))
    p_label.add_argument("--slot", required=True, help=_t("Slot-Text, z. B. SSD-1"))
    p_label.add_argument("--nur", choices=["alt", "neu"], help=_t("nur ein Label drucken (Standard: beide)"))
    p_label.add_argument("--datum", metavar=_t("TT.MM.JJJJ"), help=_t("Datum der alten Platte (Standard: heute)"))
    add_print_options(p_label)


def _ssh_settings(cfg: dict) -> tuple[float, bool]:
    ssh_cfg = cfg.get("ssh") or {}
    return ssh_cfg.get("timeout_s", 20), ssh_cfg.get("strict_host_key", True)


def _scan(args: argparse.Namespace, cfg: dict) -> zfsreplace.ZfsOverview:
    host = find_host(cfg, args.host)
    timeout_s, strict_host_key = _ssh_settings(cfg)
    ov, _stdout = zfsreplace.overview(host, runner=RUNNER, timeout_s=timeout_s, strict_host_key=strict_host_key)
    return ov


def _run_status(args: argparse.Namespace, cfg: dict, ctx: CliContext) -> int:
    ov = _scan(args, cfg)
    if args.json:
        payload = {
            "host": ov.host,
            "problems": [dataclasses.asdict(p) for p in ov.problems],
            "candidates": [{"disk": dataclasses.asdict(c.disk), "reason": c.reason} for c in ov.candidates],
        }
        ctx.out(json.dumps(payload, ensure_ascii=False, indent=2))
        return EXIT_OK
    if not ov.problems and not ov.candidates:
        ctx.out(_t("Keine defekten Geräte, alle Pools ONLINE"))
        return EXIT_OK
    for problem in ov.problems:
        ctx.out(f"{problem.name}  {problem.state}  Pool {problem.pool}  {problem.note}".rstrip())
    for candidate in ov.candidates:
        sn = candidate.disk.serial or candidate.disk.by_id or ""
        ctx.out(f"{candidate.disk.device}  {candidate.reason}  {sn}")
    return EXIT_OK


def _run_plan(args: argparse.Namespace, cfg: dict, ctx: CliContext) -> int:
    ov = _scan(args, cfg)
    plan = zfsreplace.build_plan(ov, args.alt, args.neu, slot=args.slot, today=date.today(), reason=args.grund)
    ctx.out(plan.command)
    for hint in plan.hints:
        ctx.out(_t("Hinweis: {hint}", hint=hint))
    ctx.out(plan.changelog_md)
    if args.changelog:
        args.changelog.write_text(plan.changelog_md + "\n", encoding="utf-8")
        ctx.out(_t("Changelog: {changelog}", changelog=args.changelog))
    return EXIT_OK


def _run_label(args: argparse.Namespace, cfg: dict, ctx: CliContext) -> int:
    ov = _scan(args, cfg)
    today = datetime.strptime(args.datum, "%d.%m.%Y").date() if args.datum else date.today()
    plan = zfsreplace.build_plan(ov, args.alt, args.neu, slot=args.slot, today=today)

    jobs: list[tuple[str, dict[str, str], str]] = []
    if args.nur in (None, "alt"):
        jobs.append(("platte-defekt", plan.old_label, "alt"))
    if args.nur in (None, "neu"):
        jobs.append(("datentraeger", plan.new_label, "neu"))

    original_preview = getattr(args, "preview", None)
    rc = EXIT_OK
    try:
        for template_name, values, suffix in jobs:
            if original_preview is not None:
                args.preview = original_preview.with_name(
                    f"{original_preview.stem}-{suffix}{original_preview.suffix}")
            result = print_one(ctx, args, template_name, values)
            if result != EXIT_OK:
                rc = result
    finally:
        if original_preview is not None:
            args.preview = original_preview
    return rc


def run(args: argparse.Namespace, ctx: CliContext) -> int:
    cfg = ctx.load_config()

    def _dispatch() -> int:
        if args.platte_cmd == "status":
            return _run_status(args, cfg, ctx)
        if args.platte_cmd == "plan":
            return _run_plan(args, cfg, ctx)
        if args.platte_cmd == "label":
            return _run_label(args, cfg, ctx)
        raise ValueError(_t("Unbekannter Unterbefehl 'platte {platte_cmd}'", platte_cmd=args.platte_cmd))

    return run_guarded(ctx, _dispatch)
