"""Plugin-Befehl 'tapesmith status': Druckerstatus abfragen, anzeigen, nie blockieren.

Läuft über das Druck-Backend: mit Druckdienst fragt der Dienst ab (er hält die Verbindung),
sonst direkt. `--cached` liefert nur den letzten bekannten Stand des Dienstes ohne Druckerkontakt.
"""

import argparse
import json

from tapesmith.cli_cmds.base import build_backend
from tapesmith.ipc.codec import encode_state
from tapesmith.status import preflight
from tapesmith.i18n import N_, _t

COMMAND = "status"
HELP = N_("Druckerstatus abfragen (Akku, Deckel, Band, Firmware …)")


def register(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help=_t("Status als JSON ausgeben"))
    parser.add_argument("--listen", type=float, default=0.15, help=_t("Sekunden auf Nachzügler warten"))
    parser.add_argument("--quick", action="store_true", help=_t("nur die Preflight-Abfragen (Akku, Deckel, Medium)"))
    parser.add_argument("--cached", action="store_true",
                        help=_t("nur Druckdienst: letzter bekannter Stand, kein Druckerkontakt"))


def run(args, ctx) -> int:
    profile = ctx.load_profile()
    backend = build_backend(ctx, None)
    try:
        if hasattr(backend, "listen_s"):
            backend.listen_s = args.listen
        report = backend.query_status(quick=args.quick, fresh=not args.cached)
    finally:
        backend.close()
    st = report.status
    if args.json:
        data = st.to_dict() if st is not None else {"answered": False, "values": {}, "unknown": [], "raw": ""}
        data["state"] = encode_state(report.state)
        ctx.out(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    if st is None:
        ctx.out(_t("kein Status bekannt") if args.cached else _t("keine Statusantwort"))
        return 0
    ctx.out(st.summary())
    for warning in preflight(st, profile):
        ctx.err(_t("Warnung: {warning}", warning=warning))
    return 0
