"""`tapesmith token`: API-Tokens anlegen, auflisten und widerrufen."""

import argparse
import json

from tapesmith import apitokens, config, netinfo
from tapesmith.cli_cmds.base import CliContext
from tapesmith.i18n import N_, _t

COMMAND = "token"
HELP = N_("API-Tokens verwalten (Rollen admin, drucken, familie)")


def register(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="token_cmd", required=True)

    add = sub.add_parser("add", help=_t("Token anlegen (Klartext nur jetzt sichtbar)"))
    add.add_argument("name")
    add.add_argument("--rolle", required=True, choices=apitokens.ROLES)
    add.add_argument("--json", action="store_true")

    ls = sub.add_parser("list", help=_t("Tokens auflisten (ohne Klartext)"))
    ls.add_argument("--json", action="store_true")

    rv = sub.add_parser("revoke", help=_t("Token widerrufen"))
    rv.add_argument("id_or_name", metavar=_t("ID_ODER_NAME"))


def _family_urls(ctx: CliContext, secret: str) -> list[str]:
    """Nur mit `lan.enabled = true`: sonst ist der Dienst nicht aus dem Heimnetz erreichbar, ein
    Link waere irrefuehrend (funktioniert erst nach `lan.enabled = true` und `tapesmith daemon restart`)."""
    cfg = ctx.load_config()
    if not config.setting(cfg, "lan.enabled"):
        return []
    return [f"{base}/familie#t={secret}" for base in netinfo.lan_base_urls(cfg)]


def run(args: argparse.Namespace, ctx: CliContext) -> int:
    store = apitokens.TokenStore()

    if args.token_cmd == "add":
        try:
            info, secret = store.create(args.name, args.rolle)
        except ValueError as exc:
            ctx.err(_t("Fehler: {exc}", exc=exc))
            return 1
        family_urls = _family_urls(ctx, secret) if info.role == "familie" else []
        if args.json:
            ctx.out(json.dumps(
                {"token": info.to_json(), "secret": secret, "family_urls": family_urls},
                ensure_ascii=False))
            return 0
        ctx.out(_t("Token „{name}“ (Rolle {value}) angelegt. Es wird nur jetzt angezeigt:", name=info.name, value=apitokens.ROLE_LABELS[info.role]))
        ctx.out(secret)
        if info.role == "familie":
            if family_urls:
                for url in family_urls:
                    ctx.out(_t("Familienseite: {url}", url=url))
            else:
                ctx.out(_t("LAN ist aus: lan.enabled = true setzen, dann tapesmith daemon restart"))
        return 0

    if args.token_cmd == "list":
        infos = store.list()
        if args.json:
            ctx.out(json.dumps([i.to_json() for i in infos], ensure_ascii=False))
            return 0
        if not infos:
            ctx.out(_t("Keine Tokens angelegt."))
            return 0
        ctx.out(_t("{value:<10} {value2:<20} {value3:<10} {value4:<27} zuletzt benutzt", value='id', value2='Name', value3='Rolle', value4='angelegt'))
        for i in infos:
            ctx.out(f"{i.id:<10} {i.name:<20} {apitokens.ROLE_LABELS[i.role]:<10} {i.created:<27} "
                     f"{i.last_used or '-'}")
        return 0

    if args.token_cmd == "revoke":
        try:
            info = store.revoke(args.id_or_name)
        except KeyError:
            ctx.err(_t("Fehler: Token '{id_or_name}' nicht gefunden", id_or_name=args.id_or_name))
            return 1
        except ValueError as exc:
            ctx.err(_t("Fehler: {exc}", exc=exc))
            return 1
        ctx.out(_t("Token „{name}“ widerrufen.", name=info.name))
        return 0

    raise ValueError(_t("Unbekannter Unterbefehl '{token_cmd}'", token_cmd=args.token_cmd))
