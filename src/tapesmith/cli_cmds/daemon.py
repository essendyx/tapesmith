"""Plugin-Befehl 'tapesmith daemon': Druckdienst p12d starten, stoppen, neu starten, Zustand zeigen."""

from __future__ import annotations

import argparse
import json
import time

from tapesmith.config import setting
from tapesmith.errors import EXIT_BUSY, EXIT_OK
from tapesmith.ipc.client import DaemonClient
from tapesmith.ipc.launcher import daemon_running, ensure_daemon
from tapesmith.ipc.pipe import DaemonUnavailable
from tapesmith.i18n import N_, _t

COMMAND = "daemon"
HELP = N_("Druckdienst p12d starten, stoppen, Zustand anzeigen")

SLEEP = time.sleep
STOP_POLL_S = 0.2
NOT_RUNNING = N_("Druckdienst läuft nicht")
BUSY_TEXT = N_("Druckauftrag läuft, mit --force beenden")


def register(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="daemon_cmd", required=True)
    sub.add_parser("start", help=_t("Druckdienst starten (falls er nicht schon läuft)"))
    stop = sub.add_parser("stop", help=_t("Druckdienst beenden"))
    stop.add_argument("--force", action="store_true", help=_t("auch während eines laufenden Druckauftrags"))
    restart = sub.add_parser("restart", help=_t("Druckdienst neu starten (z. B. nach einem Update)"))
    restart.add_argument("--force", action="store_true", help=_t("auch während eines laufenden Druckauftrags"))
    status = sub.add_parser("status", help=_t("läuft der Druckdienst? Zustand und Warteschlange"))
    status.add_argument("--json", action="store_true", help=_t("als JSON ausgeben"))


def connect_client(cfg: dict) -> DaemonClient:
    return DaemonClient.connect(client="cli", timeout_s=float(setting(cfg, "daemon.connect_timeout_s")))


def _start(cfg: dict, ctx) -> int:
    client = ensure_daemon(cfg, client="cli")
    try:
        ctx.out(_t("Druckdienst läuft (PID {server_pid})", server_pid=client.server_pid))
    finally:
        client.close()
    return EXIT_OK


def _stop(cfg: dict, ctx, force: bool) -> int | None:
    """Beendet den Dienst. Rückgabe: Exit-Code bei Abbruch, sonst None (beendet oder lief nicht)."""
    if not daemon_running():
        ctx.out(_t(NOT_RUNNING))
        return None
    try:
        client = connect_client(cfg)
    except DaemonUnavailable:
        ctx.out(_t(NOT_RUNNING))
        return None
    try:
        result = client.call("shutdown", {"force": bool(force)})
    finally:
        client.close()
    if not result.get("stopping", False):
        ctx.err(_t(BUSY_TEXT))
        return EXIT_BUSY
    ctx.out(_t("Druckdienst wird beendet"))
    return None


def _wait_stopped(cfg: dict) -> bool:
    deadline = time.monotonic() + float(setting(cfg, "daemon.start_timeout_s"))
    while daemon_running():
        if time.monotonic() >= deadline:
            return False
        SLEEP(STOP_POLL_S)
    return True


def _queue_summary(snapshot: dict) -> str:
    jobs = snapshot.get("jobs", [])
    waiting = sum(1 for j in jobs if j.get("state") == "wartet")
    running = sum(1 for j in jobs if j.get("state") == "läuft")
    parts = [f"{waiting} wartend"]
    if running:
        parts.append(_t("{running} läuft", running=running))
    if snapshot.get("paused"):
        parts.append("pausiert")
    if not snapshot.get("auto_retry", True):
        parts.append(_t("Auto-Nachdruck aus"))
    if snapshot.get("waiting_reason"):
        parts.append(str(snapshot["waiting_reason"]))
    return " · ".join(parts)


def _status(cfg: dict, ctx, as_json: bool) -> int:
    if not daemon_running():
        ctx.out(json.dumps({"running": False}) if as_json else _t(NOT_RUNNING))
        return EXIT_OK
    try:
        client = connect_client(cfg)
    except DaemonUnavailable:
        ctx.out(json.dumps({"running": False}) if as_json else _t(NOT_RUNNING))
        return EXIT_OK
    try:
        ping = client.call("ping")
        state = client.call("state")
        snapshot = client.call("queue.list", {"include_done": False})
    finally:
        client.close()
    if as_json:
        ctx.out(json.dumps({"running": True, "ping": ping, "state": state, "queue": snapshot},
                           ensure_ascii=False, indent=2))
        return EXIT_OK
    ctx.out(_t("Druckdienst läuft (PID {get}, Version {get2}, seit {get3:.0f} s, {get4} Client(s))", get=ping.get('pid'), get2=ping.get('version', '?'), get3=float(ping.get('uptime_s', 0.0)), get4=ping.get('clients', 0)))
    printer = str(state.get("state", "?"))
    if state.get("transport"):
        printer += f" ({state['transport']})"
    if state.get("leased"):
        printer += _t(" (reserviert)")
    ctx.out(_t("Drucker: {printer}", printer=printer))
    if state.get("last_error"):
        ctx.out(_t("Letzter Fehler: {last_error}", last_error=state['last_error']))
    ctx.out(_t("Warteschlange: {queue_summary}", queue_summary=_queue_summary(snapshot)))
    return EXIT_OK


def run(args: argparse.Namespace, ctx) -> int:
    cfg = ctx.load_config()
    if args.daemon_cmd == "start":
        return _start(cfg, ctx)
    if args.daemon_cmd == "stop":
        code = _stop(cfg, ctx, args.force)
        return code if code is not None else EXIT_OK
    if args.daemon_cmd == "restart":
        code = _stop(cfg, ctx, args.force)
        if code is not None:
            return code
        if not _wait_stopped(cfg):
            ctx.err(_t("Druckdienst beendet sich nicht, später erneut versuchen"))
            return EXIT_BUSY
        return _start(cfg, ctx)
    if args.daemon_cmd == "status":
        return _status(cfg, ctx, args.json)
    raise ValueError(_t("Unbekannter Unterbefehl '{daemon_cmd}'", daemon_cmd=args.daemon_cmd))
