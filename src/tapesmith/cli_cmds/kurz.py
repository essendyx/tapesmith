"""Plugin-Befehl 'p12 kurz' (Client-Seite): Kurz-Links direkt über die Admin-API pflegen.

Kein echter Netzzugriff standardmäßig: `TRANSPORT` ist injizierbar (Tests ersetzen es). `kurz url`
rechnet nur die Kurz-URL aus (kein Netz, kein Token nötig).
"""

from __future__ import annotations

import argparse
import dataclasses
import json

import httpx

from tapesmith.cli_cmds.base import CliContext
from tapesmith.errors import EXIT_OK
from tapesmith.integrations import settings, shortlink
from tapesmith.integrations.cliprint import run_guarded
from tapesmith.integrations.errors import NotConfigured
from tapesmith.integrations.shortlink import ShortlinkClient
from tapesmith.i18n import N_, _t

COMMAND = "kurz"
HELP = N_("Kurz-Links direkt pflegen (Client-Seite)")

# Für Tests: eigenen Transport einsetzen, ohne echtes Netz.
TRANSPORT: httpx.BaseTransport | None = None


def register(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="kurz_cmd", required=True)

    sub.add_parser("list", help=_t("alle Kurz-Links auflisten"))

    p_get = sub.add_parser("get", help=_t("einen Kurz-Link anzeigen"))
    p_get.add_argument("id")

    p_set = sub.add_parser("set", help=_t("Ziel eines Kurz-Links setzen (legt ihn an, falls nötig)"))
    p_set.add_argument("id")
    p_set.add_argument("url", help=_t("Ziel-URL, oder '-'/'none' für kein Ziel"))
    p_set.add_argument("--notiz", default="")

    p_rm = sub.add_parser("rm", help=_t("Kurz-Link löschen"))
    p_rm.add_argument("id")

    p_url = sub.add_parser("url", help=_t("nur die Kurz-URL ausgeben, ohne Netz"))
    p_url.add_argument("id")


def _client(data: dict) -> ShortlinkClient:
    return ShortlinkClient.from_settings(data, transport=TRANSPORT)


def _sync_local(data: dict, link_id: str, target: str | None, ctx: CliContext) -> None:
    """Ziel auch lokal übernehmen (Asset `ziel` bzw. Kleinanzeigen `anzeige`), damit ein späterer Druck
    das per `kurz set` gesetzte Ziel nicht mit dem alten lokalen Wert überschreibt. Legt keine
    Datenbank an, die es noch nicht gibt."""
    from tapesmith.integrations import assets as assets_mod
    from tapesmith.integrations import kleinanzeigen as ka

    if (settings.data_dir() / "assets.sqlite3").is_file():
        with assets_mod.AssetStore() as store:
            asset = store.get(link_id)
            if asset is not None and asset.ziel != target:
                store.update(asset.id, ziel=target)
                ctx.out(_t("Asset {id}: Ziel lokal übernommen", id=asset.id))
    if (settings.data_dir() / "kleinanzeigen.sqlite3").is_file():
        try:
            ka_id = ka.normalize_id(link_id, data)
        except ValueError:
            return
        if ka_id != link_id:
            return
        with ka.KaStore() as store:
            art = store.get(ka_id)
            if art is not None and art.anzeige != target:
                store.update(ka_id, anzeige=target)
                ctx.out(_t("Artikel {ka_id}: Anzeigen-Adresse lokal übernommen", ka_id=ka_id))


def _run_url(args: argparse.Namespace, data: dict, ctx: CliContext) -> int:
    base_url = data["shortlink"].get("base_url")
    if not base_url:
        raise NotConfigured(shortlink.SERVICE, _t("nicht eingerichtet: shortlink.base_url fehlt"),
                            hint=_t("In homelab.json 'shortlink.base_url' eintragen"))
    ctx.out(shortlink.short_url(base_url, args.id))
    return EXIT_OK


def _dispatch(args: argparse.Namespace, ctx: CliContext) -> int:
    data = settings.load_settings()
    if args.kurz_cmd == "url":
        return _run_url(args, data, ctx)
    with _client(data) as client:
        if args.kurz_cmd == "list":
            for link in client.list():
                ctx.out(f"{link.id}  {link.target or '-'}  {link.note}  hits={link.hits}")
            return EXIT_OK
        if args.kurz_cmd == "get":
            link = client.get(args.id)
            if link is None:
                raise KeyError(_t("Kurz-Link {id!r} gibt es nicht", id=args.id))
            ctx.out(json.dumps(dataclasses.asdict(link), ensure_ascii=False, indent=2))
            return EXIT_OK
        if args.kurz_cmd == "set":
            target = None if args.url.strip().lower() in ("-", "none") else args.url
            link = client.upsert(args.id, target, args.notiz)
            ctx.out(_t("Gesetzt: {id} -> {value}", id=link.id, value=link.target or '-'))
            _sync_local(data, link.id, target, ctx)
            return EXIT_OK
        if args.kurz_cmd == "rm":
            ok = client.delete(args.id)
            ctx.out(_t("Gelöscht") if ok else _t("Gab es nicht"))
            return EXIT_OK
    raise ValueError(_t("Unbekannter Unterbefehl 'kurz {kurz_cmd}'", kurz_cmd=args.kurz_cmd))


def run(args: argparse.Namespace, ctx: CliContext) -> int:
    return run_guarded(ctx, lambda: _dispatch(args, ctx))
