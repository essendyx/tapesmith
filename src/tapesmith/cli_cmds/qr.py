"""`tapesmith qr`: QR-Label aus URL, Text, WLAN oder vCard bauen und drucken."""

import argparse
import dataclasses
import getpass
import os

from tapesmith.cli_cmds.base import CliContext, add_print_options
from tapesmith.document.render import render_spec
from tapesmith.labelmeta import qr_meta
from tapesmith.render.qrcontent import (
    best_error_level,
    build_qr_spec,
    capacity_report,
    text_content,
    url_content,
    vcard_content,
    wifi_content,
)
from tapesmith.tape.profiles import current_tape
from tapesmith.i18n import N_, _t

COMMAND = "qr"
HELP = N_("QR-Label: URL, Text, WLAN oder vCard")

GETPASS = getpass.getpass


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--line", action="append", default=[], help=_t("zusätzliche Textzeile rechts (max. 2)"))
    parser.add_argument("--error", default="auto", choices=["l", "m", "q", "h", "auto"],
                        help=_t("Fehlerkorrektur (Standard: automatisch das kleinste passende Level)"))
    parser.add_argument("--max-mm", type=float, help=_t("maximale Labellänge in mm"))
    parser.add_argument("--show-data", action="store_true",
                        help=_t("QR-Inhalt (bei sensiblen Werten nur die Anzeige) ausgeben"))
    add_print_options(parser)


def register(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="qr_kind", required=True)

    p_url = sub.add_parser("url", help=_t("URL-QR"))
    p_url.add_argument("url")
    p_url.add_argument("--upper", action="store_true", help=_t("Link in Großbuchstaben (nur für Kurz-Links)"))
    _common(p_url)

    p_text = sub.add_parser("text", help=_t("Text-QR"))
    p_text.add_argument("text")
    _common(p_text)

    p_wifi = sub.add_parser("wifi", help=_t("WLAN-QR"))
    p_wifi.add_argument("--ssid", required=True)
    p_wifi.add_argument("--security", default="WPA", choices=["WPA", "WEP", "nopass"])
    p_wifi.add_argument("--hidden", action="store_true", help=_t("Netz ist versteckt (H:true)"))
    pw = p_wifi.add_mutually_exclusive_group()
    pw.add_argument("--password-prompt", action="store_true", help=_t("Passwort interaktiv abfragen (getpass)"))
    pw.add_argument("--password-stdin", action="store_true", help=_t("Passwort als eine Zeile von stdin lesen"))
    pw.add_argument("--password-env", metavar="VAR", help=_t("Passwort aus dieser Umgebungsvariable lesen"))
    _common(p_wifi)

    p_vcard = sub.add_parser("vcard", help=_t("vCard-QR"))
    p_vcard.add_argument("--name", required=True)
    p_vcard.add_argument("--phone", default="")
    p_vcard.add_argument("--email", default="")
    p_vcard.add_argument("--org", default="")
    p_vcard.add_argument("--url", default="")
    _common(p_vcard)


def read_password(args: argparse.Namespace, ctx: CliContext) -> str:
    """Liest das WLAN-Passwort aus genau einer Quelle. Nie als Kommandozeilenargument,
    das würde in der Shell-History landen."""
    sources = (args.password_prompt, args.password_stdin, bool(args.password_env))
    if sum(bool(s) for s in sources) != 1:
        raise ValueError(
            _t("Genau eine Passwortquelle angeben: --password-prompt, --password-stdin oder --password-env")
        )
    if args.password_prompt:
        return GETPASS(_t("WLAN-Passwort: "))
    if args.password_stdin:
        return ctx.stdin.readline().rstrip("\n")
    value = os.environ.get(args.password_env)
    if value is None:
        raise ValueError(_t("Umgebungsvariable '{password_env}' ist nicht gesetzt", password_env=args.password_env))
    return value


def run(args: argparse.Namespace, ctx: CliContext) -> int:
    if len(args.line) > 2:
        raise ValueError(_t("höchstens 2 zusätzliche Zeilen erlaubt, {count} angegeben", count=len(args.line)))

    if args.qr_kind == "url":
        content = url_content(args.url, uppercase=args.upper)
    elif args.qr_kind == "text":
        content = text_content(args.text)
    elif args.qr_kind == "wifi":
        password = "" if args.security == "nopass" else read_password(args, ctx)
        content = wifi_content(args.ssid, password, args.security, args.hidden)
    else:
        content = vcard_content(args.name, args.phone, args.email, args.org, args.url)

    profile = ctx.load_profile()
    error = best_error_level(content, profile) if args.error == "auto" else args.error
    cap = capacity_report(content, profile, error)
    ctx.err(_t("Info: {text}", text=cap.text()))
    for warning in cap.warnings:
        ctx.err(_t("Warnung: {warning}", warning=warning))

    if args.show_data:
        ctx.out(content.display if content.secret else content.data)

    if getattr(args, "hexlog", None) and content.secret:
        ctx.err(_t("Warnung: Hex-Log enthält Rasterdaten mit sensiblen Werten"))

    spec = build_qr_spec(content, args.line, error, args.max_mm)
    tape = current_tape(ctx.load_config())
    result = render_spec(spec, profile, tape)
    meta = qr_meta(content, args.line, source="cli", spec=spec)
    # capacity_report hat seine Warnungen schon ausgegeben, nicht ein zweites Mal melden.
    reported = set(cap.warnings)
    result = dataclasses.replace(result, warnings=[w for w in result.warnings if w not in reported])
    ctx.emit_label(result, meta)
    return 0
