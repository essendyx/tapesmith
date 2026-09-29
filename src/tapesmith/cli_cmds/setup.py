"""CLI-Befehl 'p12 setup': Verbindungsassistent. Port finden, testen, speichern."""

import json
import time
from datetime import datetime

from tapesmith import config
from tapesmith.cli_cmds.base import CliContext
from tapesmith.printer import PrinterSession
from tapesmith.render.compose import LabelSpec, render_label
from tapesmith.setup import run_setup
from tapesmith.transport.resolve import open_transport
from tapesmith.i18n import N_, _t

COMMAND = "setup"
HELP = N_("Drucker einrichten: Port finden, testen, speichern")

SLEEP = time.sleep


def register(parser) -> None:
    parser.add_argument("--mac", help=_t("MAC-Adresse des Druckers (z. B. 001122334455)"))
    parser.add_argument("--port", help=_t("COM-Port statt Suche über die MAC (z. B. COM4)"))
    parser.add_argument("--test-label", action="store_true", help=_t("nach der Einrichtung ein Testlabel drucken"))
    parser.add_argument("--json", action="store_true", help=_t("Ergebnis als JSON ausgeben"))


def run(args, ctx: CliContext) -> int:
    cfg = ctx.load_config()

    def probe(port):
        profile = ctx.load_profile()
        transport = open_transport(port, args.mac or cfg["mac"], args.hexlog,
                                    open_timeout=float(cfg["connect_timeout_s"]))
        with PrinterSession(transport, profile, sleep=SLEEP) as session:
            return session.handshake()

    def test_print(port):
        profile = ctx.load_profile()
        spec = LabelSpec(
            lines=("Tapesmith", "Test " + datetime.now().strftime("%d.%m.%Y %H:%M")),
            max_length_mm=40,
        )
        result = render_label(spec, profile)
        transport = open_transport(port, args.mac or cfg["mac"], args.hexlog,
                                    open_timeout=float(cfg["connect_timeout_s"]))
        with PrinterSession(transport, profile, sleep=SLEEP) as session:
            session.print_image(result.head)

    profile = ctx.load_profile()
    status_map = getattr(profile, "status_map", None)
    codes = status_map() if status_map is not None else None

    result = run_setup(
        mac=args.mac,
        port=args.port,
        probe=probe,
        save=config.save_config,
        test_print=test_print if args.test_label else None,
        codes=codes,
    )

    if args.json:
        ctx.out(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        for step in result.steps:
            marker = "[OK]    " if step.ok else _t("[FEHLER]")
            ctx.out(f"{marker} {step.name}: {step.detail}")
            if step.hint and not step.ok:
                ctx.out(f"         -> {step.hint}")

    return result.exit_code
