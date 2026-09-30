"""Plugin-Befehl 'tapesmith asset': Asset-Nummern reservieren, verwalten und als `asset-kurz` drucken.

Kein echter Netzzugriff standardmäßig: `TRANSPORT` ist injizierbar (Tests ersetzen es), Default
ist der echte Kurz-Link-Dienst über `integrations.shortlink`. Nummern kommen aus dem
zentralen Nummernkreis-Ordner (`numbering.numbering_dir(cfg)`), nie aus einer eigenen Datei.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
from pathlib import Path

import httpx

from tapesmith import numbering
from tapesmith.cli_cmds.base import CliContext, positive_int
from tapesmith.errors import EXIT_ERROR, EXIT_OK
from tapesmith.integrations import assets as assets_mod
from tapesmith.integrations import settings
from tapesmith.integrations.cliprint import add_series_options, print_rows, run_guarded
from tapesmith.i18n import N_, _t

COMMAND = "asset"
HELP = N_("Asset-Nummern reservieren, verwalten und als asset-kurz drucken")

# Für Tests: eigenen Transport für den Kurz-Link-Dienst einsetzen, ohne echtes Netz.
TRANSPORT: httpx.BaseTransport | None = None


def register(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="asset_cmd", required=True)

    p_neu = sub.add_parser("neu", help=_t("neue Asset-Nummer(n) reservieren"))
    p_neu.add_argument("count", nargs="?", type=positive_int, default=1, metavar="N")
    p_neu.add_argument("--bezeichnung", default="")
    p_neu.add_argument("--kategorie", default="")
    p_neu.add_argument("--standort", default="")
    p_neu.add_argument("--sn", dest="seriennummer", default="")
    p_neu.add_argument("--host", default="")
    p_neu.add_argument("--ziel", dest="ziel", default=None, metavar="URL")
    p_neu.add_argument("--paperless", dest="paperless_doc", type=int, default=None, metavar="ID")
    p_neu.add_argument("--print", dest="do_print", action="store_true", help=_t("sofort als Serie drucken"))
    add_series_options(p_neu, template="asset-kurz")

    p_list = sub.add_parser("list", help=_t("Assets auflisten"))
    p_list.add_argument("--status", default=None, choices=assets_mod.STATUSES)
    p_list.add_argument("--suche", default="")
    p_list.add_argument("--json", action="store_true")

    p_show = sub.add_parser("show", help=_t("ein Asset anzeigen"))
    p_show.add_argument("id")

    p_set = sub.add_parser("set", help=_t("Felder eines Assets setzen"))
    p_set.add_argument("id")
    p_set.add_argument("felder", nargs="+", metavar=_t("feld=wert"))

    p_void = sub.add_parser("void", help=_t("Asset verwerfen (Fehldruck)"))
    p_void.add_argument("id")
    p_void.add_argument("--grund", required=True)

    p_import = sub.add_parser("import", help=_t("vorhandene, schon geklebte Nummer übernehmen"))
    p_import.add_argument("id")
    p_import.add_argument("felder", nargs="*", metavar=_t("feld=wert"))

    p_export = sub.add_parser("export", help=_t("Register als CSV exportieren"))
    p_export.add_argument("datei", type=Path)

    p_print = sub.add_parser("print", help=_t("ein oder mehrere Assets drucken"))
    p_print.add_argument("ids", nargs="+")
    add_series_options(p_print, template="asset-kurz")


def _asdict(asset: assets_mod.Asset) -> dict:
    return dataclasses.asdict(asset)


def _is_real_print(args: argparse.Namespace) -> bool:
    """Echter Druck (kein --preview, kein --dry-run): nur dann wird der Kurz-Link im Dienst gesetzt."""
    return not (getattr(args, "dry_run", False) or getattr(args, "preview", None))


def _rows_for(ctx: CliContext, args: argparse.Namespace, data: dict,
              assets: list[assets_mod.Asset]) -> list[dict[str, str]]:
    rows = []
    for asset in assets:
        link, warnings = assets_mod.asset_link(data, asset, sync=_is_real_print(args), transport=TRANSPORT)
        for warning in warnings:
            ctx.err(_t("Hinweis: {warning}", warning=warning))
        rows.append(assets_mod.label_values(asset, link))
    return rows


def _run_neu(args: argparse.Namespace, cfg: dict, ctx: CliContext, store: assets_mod.AssetStore) -> int:
    data = settings.load_settings()
    if getattr(args, "dry_run", False):
        ranges = numbering.NumberRanges(numbering.numbering_dir(cfg) / numbering.FILE_NAME)
        for asset_id in assets_mod.peek_next_ids(ranges, data, args.count):
            ctx.out(asset_id)
        return EXIT_OK
    ranges = numbering.NumberRanges(numbering.numbering_dir(cfg) / numbering.FILE_NAME)
    new_assets = store.reserve(ranges, data, args.count, bezeichnung=args.bezeichnung,
                               kategorie=args.kategorie, standort=args.standort,
                               seriennummer=args.seriennummer, host=args.host, ziel=args.ziel,
                               paperless_doc=args.paperless_doc, notiz="")
    for asset in new_assets:
        ctx.out(asset.id)
    if args.do_print:
        rows = _rows_for(ctx, args, data, new_assets)
        return print_rows(ctx, args, args.template, rows)
    return EXIT_OK


def _run_list(args: argparse.Namespace, ctx: CliContext, store: assets_mod.AssetStore) -> int:
    found = store.list(status=args.status, query=args.suche)
    if args.json:
        ctx.out(json.dumps([_asdict(a) for a in found], ensure_ascii=False, indent=2))
        return EXIT_OK
    for asset in found:
        ctx.out(f"{asset.id}  {asset.bezeichnung}  {asset.kategorie}  {asset.standort}  {asset.status}")
    return EXIT_OK


def _run_show(args: argparse.Namespace, ctx: CliContext, store: assets_mod.AssetStore) -> int:
    asset = store.get(args.id)
    if asset is None:
        raise KeyError(_t("Asset {id!r} gibt es nicht", id=args.id))
    ctx.out(json.dumps(_asdict(asset), ensure_ascii=False, indent=2))
    return EXIT_OK


def _run_set(args: argparse.Namespace, ctx: CliContext, store: assets_mod.AssetStore) -> int:
    from tapesmith.cli_cmds.base import parse_sets

    changes = parse_sets(args.felder)
    asset = store.update(args.id, **changes)
    ctx.out(_t("Aktualisiert: {id}", id=asset.id))
    return EXIT_OK


def _run_void(args: argparse.Namespace, cfg: dict, ctx: CliContext, store: assets_mod.AssetStore) -> int:
    data = settings.load_settings()
    ranges = numbering.NumberRanges(numbering.numbering_dir(cfg) / numbering.FILE_NAME)
    asset = store.void(ranges, data, args.id, args.grund)
    ctx.out(_t("Verworfen: {id}", id=asset.id))
    return EXIT_OK


def _run_import(args: argparse.Namespace, ctx: CliContext, store: assets_mod.AssetStore) -> int:
    from tapesmith.cli_cmds.base import parse_sets

    changes = parse_sets(args.felder) if args.felder else {}
    asset = store.add_existing(args.id, **changes)
    ctx.out(_t("Übernommen: {id}", id=asset.id))
    return EXIT_OK


def _run_export(args: argparse.Namespace, ctx: CliContext, store: assets_mod.AssetStore) -> int:
    args.datei.write_text(store.export_csv(), encoding="utf-8")
    ctx.out(_t("Exportiert: {datei}", datei=args.datei))
    return EXIT_OK


def _run_print(args: argparse.Namespace, ctx: CliContext, store: assets_mod.AssetStore) -> int:
    data = settings.load_settings()
    found = []
    missing = []
    for asset_id in args.ids:
        asset = store.get(asset_id)
        if asset is None:
            missing.append(asset_id)
        else:
            found.append(asset)
    if missing:
        ctx.err(_t("Unbekannte Assets: {items}", items=', '.join(missing)))
        return EXIT_ERROR
    rows = _rows_for(ctx, args, data, found)
    return print_rows(ctx, args, args.template, rows)


def _dispatch(args: argparse.Namespace, ctx: CliContext) -> int:
    cfg = ctx.load_config()
    with assets_mod.AssetStore() as store:
        if args.asset_cmd == "neu":
            return _run_neu(args, cfg, ctx, store)
        if args.asset_cmd == "list":
            return _run_list(args, ctx, store)
        if args.asset_cmd == "show":
            return _run_show(args, ctx, store)
        if args.asset_cmd == "set":
            return _run_set(args, ctx, store)
        if args.asset_cmd == "void":
            return _run_void(args, cfg, ctx, store)
        if args.asset_cmd == "import":
            return _run_import(args, ctx, store)
        if args.asset_cmd == "export":
            return _run_export(args, ctx, store)
        if args.asset_cmd == "print":
            return _run_print(args, ctx, store)
    raise ValueError(_t("Unbekannter Unterbefehl 'asset {asset_cmd}'", asset_cmd=args.asset_cmd))


def run(args: argparse.Namespace, ctx: CliContext) -> int:
    return run_guarded(ctx, lambda: _dispatch(args, ctx))
