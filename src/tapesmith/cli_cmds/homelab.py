"""Plugin-Befehl 'p12 homelab': Einstellungen der Homelab-Integrationen (homelab.json).

Unterbefehle: `show` (öffentliche Sicht ohne Token-Werte), `set KEY VALUE`, `check` (je Dienst
eingerichtet und Token vorhanden, ohne Netz), `secret DIENST/BENUTZER` (Token verdeckt in den
Windows-Anmeldeinformationsspeicher) und `path`.
"""

from __future__ import annotations

import argparse
import getpass
import json

from tapesmith.cli_cmds.base import CliContext
from tapesmith.errors import EXIT_OK
from tapesmith.integrations import credentials, settings
from tapesmith.integrations.cliprint import run_guarded
from tapesmith.i18n import N_, _t

COMMAND = "homelab"
HELP = N_("Einstellungen der Homelab-Integrationen (homelab.json) anzeigen, setzen und prüfen")


def register(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="homelab_cmd", required=True)
    sub.add_parser("show", help=_t("Einstellungen als JSON (ohne Token-Werte)"))
    p_set = sub.add_parser("set", help=_t("einen Wert setzen, z. B. assets.prefix '\"AS-\"'"))
    p_set.add_argument("key", help=_t("sektion.schlüssel"))
    p_set.add_argument("value", help=_t("Wert als JSON (true, 5, null, \"Text\", [...]) oder Text"))
    sub.add_parser("check", help=_t("je Dienst prüfen: eingerichtet, Token vorhanden (ohne Netz)"))
    p_secret = sub.add_parser("secret", help=_t("Token im Windows-Anmeldeinformationsspeicher hinterlegen"))
    p_secret.add_argument("name", metavar=_t("DIENST/BENUTZER"), help=_t("z. B. tapesmith/paperless"))
    p_secret.add_argument("--stdin", action="store_true", help=_t("Wert aus der Standardeingabe lesen"))
    sub.add_parser("path", help=_t("Pfad der Datei homelab.json"))


def _parse_value(text: str):
    try:
        return json.loads(text)
    except ValueError:
        return text


def _show(ctx: CliContext) -> int:
    view = settings.public_view(settings.load_settings())
    ctx.out(json.dumps(view, ensure_ascii=False, indent=2))
    return EXIT_OK


def _set(args: argparse.Namespace, ctx: CliContext) -> int:
    value = _parse_value(args.value)
    settings.set_setting(args.key, value)
    ctx.out(f"{args.key} = {json.dumps(value, ensure_ascii=False)}")
    return EXIT_OK


def _yes_no(value: bool | None) -> str:
    if value is None:
        return "-"
    return "ok" if value else "fehlt"


def _check(ctx: CliContext) -> int:
    services = settings.check_services(settings.load_settings())
    width = max(len(_t("Dienst")), *(len(s["label"]) for s in services))
    ctx.out(f"{'Dienst':<{width}}  {'Eingerichtet':<12}  {'Token':<5}  Hinweis")
    for service in services:
        ctx.out(f"{service['label']:<{width}}  {_yes_no(service['configured']):<12}  "
                f"{_yes_no(service['token_set']):<5}  {service['detail']}")
    return EXIT_OK


def _secret(args: argparse.Namespace, ctx: CliContext) -> int:
    ref = credentials.check_ref(f"keyring:{args.name}")
    if args.stdin:
        value = ctx.stdin.readline().strip()
    else:
        value = getpass.getpass(f"Token für {args.name} (Eingabe verdeckt): ").strip()
    if not value:
        raise ValueError(_t("Kein Wert eingegeben, nichts gespeichert"))
    credentials.write_secret(ref, value)
    ctx.out(_t("Gespeichert: {describe_ref}", describe_ref=credentials.describe_ref(ref)))
    return EXIT_OK


def _dispatch(args: argparse.Namespace, ctx: CliContext) -> int:
    cmd = args.homelab_cmd
    if cmd == "show":
        return _show(ctx)
    if cmd == "set":
        return _set(args, ctx)
    if cmd == "check":
        return _check(ctx)
    if cmd == "secret":
        return _secret(args, ctx)
    if cmd == "path":
        ctx.out(str(settings.settings_path()))
        return EXIT_OK
    raise ValueError(_t("Unbekannter Unterbefehl 'homelab {cmd}'", cmd=cmd))


def run(args: argparse.Namespace, ctx: CliContext) -> int:
    return run_guarded(ctx, lambda: _dispatch(args, ctx))
