"""Plugin-Befehl 'p12 telegram': Testnachricht senden, Konfiguration und Zustand anzeigen."""

from __future__ import annotations

import argparse

from tapesmith.automation import telegram
from tapesmith.errors import EXIT_ERROR, EXIT_OK
from tapesmith.i18n import N_, _t

COMMAND = "telegram"
HELP = N_("Telegram-Meldungen des Druckdienstes testen und anzeigen")

# Poster für `p12 telegram test`, Standard httpx.post (Modul-Attribut, Tests ersetzen es per monkeypatch).
HTTP_POST = None


def register(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="telegram_cmd", required=True)
    sub.add_parser("test", help=_t("Testnachricht mit der aktuellen Konfiguration senden"))
    sub.add_parser("status", help=_t("an/aus, Chat-ID, Token-Referenz, Ruhezeit, Schwellen anzeigen"))


def _fmt_m(value: float) -> str:
    return f"{value:.1f}".replace(".", ",")


def _token_state(cfg: dict) -> str:
    ref = telegram.setting(cfg, "token_ref")
    describe = telegram.describe_ref(ref)
    try:
        vorhanden = bool(telegram.read_secret(ref)) if ref else False
    except Exception:  # noqa: BLE001: jede Art von Secret-Fehler zählt als "fehlt"
        vorhanden = False
    return f"Token: {describe} ({'vorhanden' if vorhanden else 'fehlt'})"


def _status(ctx, cfg: dict) -> int:
    enabled = bool(telegram.setting(cfg, "enabled"))
    chat_id = telegram.setting(cfg, "chat_id")
    quiet = telegram.setting(cfg, "quiet_hours")
    ctx.out(_t("Telegram-Meldungen: {value}", value='an' if enabled else 'aus'))
    ctx.out(_t("Chat-ID: {value}", value='fehlt' if telegram._chat_id_missing(chat_id) else 'gesetzt'))
    ctx.out(_token_state(cfg))
    ctx.out(_t("Ruhezeit: {value}", value=quiet if quiet else 'keine'))
    ctx.out(_t("Schwellen: Warteschlange ab {q} min, Offline ab {o} min, Rolle ab {r} m").format(
        q=telegram.setting(cfg, "queue_stuck_min"), o=telegram.setting(cfg, "offline_min"),
        r=_fmt_m(float(telegram.setting(cfg, "roll_low_m")))))
    ctx.out(_t("Arten: Warteschlange {a}, Offline {b}, Druckfehler {c}, Restmeter {d}").format(
        a="an" if telegram.setting(cfg, "notify_queue") else "aus",
        b="an" if telegram.setting(cfg, "notify_offline") else "aus",
        c="an" if telegram.setting(cfg, "notify_error") else "aus",
        d="an" if telegram.setting(cfg, "notify_roll") else "aus"))
    return EXIT_OK


def _test(ctx, cfg: dict) -> int:
    ok, err = telegram.send_test(cfg, http_post=HTTP_POST)
    if ok:
        ctx.out(_t("Gesendet."))
        return EXIT_OK
    ctx.err(_t("Fehler: {err}", err=err))
    return EXIT_ERROR


def run(args: argparse.Namespace, ctx) -> int:
    cfg = ctx.load_config()
    if args.telegram_cmd == "status":
        return _status(ctx, cfg)
    if args.telegram_cmd == "test":
        return _test(ctx, cfg)
    raise ValueError(_t("Unbekannter Unterbefehl '{telegram_cmd}'", telegram_cmd=args.telegram_cmd))
