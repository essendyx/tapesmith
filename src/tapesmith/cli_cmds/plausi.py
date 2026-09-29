"""Plugin-Befehl 'p12 plausi': Plausibilitätsprüfung vor dem Druck.

`p12 plausi VORLAGE feld=wert … [--vault] [--json] [--streng]`. Der Server blockiert nie
(Warnung statt Sperre): normaler Exit-Code 0 auch bei einem Konflikt, `--streng` liefert dafür
Exit 1 (für Skripte). `TRANSPORT` und `RESOLVER` ersetzen Tests.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
from collections.abc import Callable

from tapesmith.cli_cmds.base import CliContext, parse_sets
from tapesmith.errors import EXIT_ERROR, EXIT_OK
from tapesmith.integrations import cliprint, scancache, settings
from tapesmith.integrations.assets import AssetStore
from tapesmith.integrations.obsidian import VaultClient
from tapesmith.integrations.plausi import Context, Finding, check, default_resolver, worst
from tapesmith.integrations.tia606 import KabelRegister
from tapesmith.templates.store import find_template
from tapesmith.i18n import N_, _t

COMMAND = "plausi"
HELP = N_("Plausibilitätsprüfung vor dem Druck: SN, IP, DNS, Asset, Kabel")

# Für Tests: httpx-Transport des Vault-Clients und Auflöser für DNS.
TRANSPORT = None
RESOLVER: Callable[[str], list[str]] | None = None

DNS_TIMEOUT_S = 2.0
_LEVEL_RANK = {"konflikt": 0, "warnung": 1, "info": 2}


def register(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("template", metavar=_t("VORLAGE"))
    parser.add_argument("sets", nargs="*", metavar=_t("FELD=WERT"))
    parser.add_argument("--vault", action="store_true", help=_t("auch den Obsidian-Vault durchsuchen"))
    parser.add_argument("--json", action="store_true", help=_t("Ausgabe als JSON"))
    parser.add_argument("--streng", action="store_true", help=_t("Exit 1 bei einem Konflikt (für Skripte)"))


def _timed_resolver(resolver: Callable[[str], list[str]], timeout_s: float) -> Callable[[str], list[str]]:
    def call(host: str) -> list[str]:
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = pool.submit(resolver, host)
        try:
            return future.result(timeout=timeout_s)
        except concurrent.futures.TimeoutError:
            return []
        finally:
            # kein `with`-Block: dessen __exit__ würde shutdown(wait=True) rufen und auf den
            # ggf. weiterhin hängenden Resolver-Thread warten, das Zeitlimit wäre wirkungslos.
            pool.shutdown(wait=False)

    return call


def _print_findings(ctx: CliContext, findings: list[Finding], result_worst: str | None, as_json: bool) -> None:
    if as_json:
        ctx.out(json.dumps({"findings": [f.__dict__ for f in findings], "worst": result_worst},
                           ensure_ascii=False, indent=2))
        return
    if not findings:
        ctx.out(_t("Keine Befunde"))
        return
    for f in findings:
        suffix = f" [{f.field}]" if f.field else ""
        ctx.out(f"{f.level}: {f.message}{suffix}")


def _run(args: argparse.Namespace, ctx: CliContext) -> int:
    find_template(args.template)
    values = parse_sets(args.sets)
    data = settings.load_settings()
    findings: list[Finding] = []

    assets = None
    assets_path = settings.data_dir() / "assets.sqlite3"
    if assets_path.exists():
        try:
            assets = AssetStore()
        except Exception as exc:  # noqa: BLE001 (Quelle isolieren wie in routes_plausi)
            findings.append(Finding("info", None, "quelle_fehlt", _t("Asset-Register nicht lesbar: {exc}", exc=exc)))

    kabel = None
    kabel_path = settings.data_dir() / "kabel.json"
    if kabel_path.exists():
        kabel = KabelRegister()

    vault = None
    if args.vault:
        vault = VaultClient.from_settings(data, transport=TRANSPORT)

    resolver = None
    if data["plausi"]["dns_check"]:
        base_resolver = RESOLVER or default_resolver
        timeout = min(float(data["obsidian"].get("timeout_s", 10.0)), DNS_TIMEOUT_S)
        resolver = _timed_resolver(base_resolver, timeout)

    plausi_ctx = Context(scans=scancache.all_scans(), networks=data["plausi"]["networks"], assets=assets,
                         kabel=kabel, vault=vault, resolver=resolver)
    try:
        findings.extend(check(args.template, values, plausi_ctx))
    finally:
        if assets is not None:
            assets.close()
        if vault is not None:
            vault.close()

    findings.sort(key=lambda f: _LEVEL_RANK[f.level])
    result_worst = worst(findings)
    _print_findings(ctx, findings, result_worst, args.json)

    if args.streng and result_worst == "konflikt":
        return EXIT_ERROR
    return EXIT_OK


def run(args: argparse.Namespace, ctx: CliContext) -> int:
    return cliprint.run_guarded(ctx, lambda: _run(args, ctx))
