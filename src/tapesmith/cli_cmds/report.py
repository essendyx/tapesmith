"""`p12 report`: Support-Bericht „Problem melden“ als Zip speichern (CLI bleibt Deutsch).

Läuft der Druckdienst, kommen Druckerstatus (letzter bekannter Stand, kein Druckerkontakt) und
Warteschlange von ihm; sonst entsteht der Bericht ohne Status. Der Dienst wird nie gestartet.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from tapesmith import support
from tapesmith.i18n import N_, _t

COMMAND = "report"
HELP = N_("Support-Bericht (Zip ohne Tokens) für „Problem melden“ speichern")


def daemon_status(cfg: dict, *, connector: Callable | None = None, timeout_s: float = 0.5) -> dict | None:
    """Status und Warteschlange vom laufenden Druckdienst oder None (jede Störung heißt: kein Dienst)."""
    try:
        if connector is None:
            from tapesmith.ipc.client import DaemonClient

            connector = DaemonClient.connect
        client = connector(client="cli", timeout_s=timeout_s)
    except Exception:  # noqa: BLE001
        return None
    try:
        from tapesmith.ipc.codec import decode_report
        from tapesmith.webapi.convert import status_json

        report = decode_report(client.call("status", {"quick": False, "fresh": False}, timeout=5.0))
        status = status_json(report, now=datetime.now(), mac=cfg.get("mac"))
        try:
            status["queue"] = client.call("queue.list", {"include_done": False}, timeout=5.0)
        except Exception:  # noqa: BLE001
            status["queue"] = None
        return status
    except Exception:  # noqa: BLE001
        return None
    finally:
        try:
            client.close()
        except Exception:  # noqa: BLE001
            pass


# Tests ersetzen die Statusquelle (kein Druckdienst, keine Named Pipe).
STATUS_LOADER: Callable[[dict], dict | None] = daemon_status


def register(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--out", type=Path, metavar=_t("DATEI.zip"),
                        help=_t("Zieldatei (Standard: tapesmith-bericht-<datum>.zip im aktuellen Ordner)"))


def run(args: argparse.Namespace, ctx) -> int:
    now = datetime.now()
    try:
        cfg = ctx.load_config()
    except Exception as exc:  # noqa: BLE001 (kaputte Konfiguration gehört in den Bericht)
        from tapesmith import config

        cfg = dict(config.DEFAULTS)
        cfg["konfiguration_fehler"] = str(exc)
    status = STATUS_LOADER(cfg)
    target = args.out if args.out is not None else Path.cwd() / support.report_filename(now)
    data = support.build_report(cfg, status=status, now=now)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    ctx.out(_t("Bericht gespeichert: {target} (keine Tokens enthalten)", target=target))
    return 0
