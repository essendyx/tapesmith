"""`tapesmith secret`: MQTT-Passwort und Telegram-Bot-Token pflegen (Secret-Referenzen)."""

import argparse
import getpass as _getpass_module

from tapesmith import config, secretref
from tapesmith.cli_cmds.base import CliContext
from tapesmith.i18n import N_, _t

COMMAND = "secret"
HELP = N_("MQTT-Passwort und Telegram-Bot-Token pflegen (Secret-Referenzen)")

NAMES = ("mqtt", "telegram")

# Modul-Attribute für Tests (Fakes statt echtem Credential Manager/echter Konsole).
KEYRING = None
GETPASS = _getpass_module.getpass


def register(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="secret_cmd", required=True)

    st = sub.add_parser("set", help=_t("Wert speichern (nur für keyring:-Referenzen)"))
    st.add_argument("name", choices=NAMES)
    st.add_argument("--stdin", action="store_true", help=_t("Wert von stdin lesen statt abzufragen"))

    ch = sub.add_parser("check", help=_t("prüfen, ob ein Wert vorliegt (ohne ihn anzuzeigen)"))
    ch.add_argument("name", choices=NAMES)


def _ref_key(name: str) -> str:
    return "mqtt.password_ref" if name == "mqtt" else "telegram.token_ref"


def _ref(ctx: CliContext, name: str) -> str | None:
    cfg = ctx.load_config()
    return config.setting(cfg, _ref_key(name))


def run(args: argparse.Namespace, ctx: CliContext) -> int:
    ref = _ref(ctx, args.name)

    if args.secret_cmd == "set":
        if not ref or not ref.startswith("keyring:"):
            describe = secretref.describe_ref(ref)
            ctx.err(_t("Fehler: Die Referenz zeigt auf {describe}; den Wert dort pflegen", describe=describe))
            return 1
        if args.stdin:
            value = ctx.stdin.readline().rstrip("\r\n")
        else:
            value = GETPASS(_t("Wert (wird nicht angezeigt): "))
        try:
            secretref.write_secret(ref, value, keyring_module=KEYRING)
        except ValueError as exc:
            ctx.err(_t("Fehler: {exc}", exc=exc))
            return 1
        ctx.out(_t("Gespeichert: {describe_ref}", describe_ref=secretref.describe_ref(ref)))
        return 0

    if args.secret_cmd == "check":
        describe = secretref.describe_ref(ref)
        if not ref:
            ctx.err(f"fehlt: {describe}")
            return 1
        try:
            secretref.read_secret(ref, keyring_module=KEYRING)
        except secretref.SecretMissing as exc:
            ctx.err(f"fehlt: {exc}")
            return 1
        ctx.out(_t("vorhanden ({describe})", describe=describe))
        return 0

    raise ValueError(_t("Unbekannter Unterbefehl '{secret_cmd}'", secret_cmd=args.secret_cmd))
