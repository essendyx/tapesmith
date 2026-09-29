"""Druckdienst p12d bei Bedarf starten und prüfen, ob er läuft."""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence

from tapesmith import launch, paths
from tapesmith.config import setting
from tapesmith.ipc.client import DaemonClient
from tapesmith.ipc.pipe import DaemonUnavailable
from tapesmith.i18n import _t


def ensure_daemon(cfg: dict, *, client: str = "cli",
                  spawn: Callable[[Sequence[str]], int] = launch.spawn_detached,
                  argv: Sequence[str] | None = None,
                  connector: Callable[..., DaemonClient] = DaemonClient.connect,
                  timeout_s: float | None = None, poll_s: float = 0.2, sleep=time.sleep,
                  clock=time.monotonic) -> DaemonClient:
    """Verbindet mit dem laufenden Dienst oder startet ihn (losgelöst) und wartet, bis er antwortet."""
    connect_timeout = float(setting(cfg, "daemon.connect_timeout_s"))
    try:
        return connector(client=client, timeout_s=connect_timeout)
    except DaemonUnavailable:
        pass
    try:
        spawn(list(argv) if argv is not None else launch.app_argv("daemon"))
    except (RuntimeError, OSError) as exc:
        raise DaemonUnavailable(_t("Druckdienst startet nicht: {exc}", exc=exc)) from exc
    limit = float(timeout_s if timeout_s is not None else setting(cfg, "daemon.start_timeout_s"))
    deadline = clock() + limit
    while True:
        try:
            return connector(client=client, timeout_s=max(poll_s, 0.05))
        except DaemonUnavailable:
            pass
        if clock() >= deadline:
            break
        sleep(poll_s)
    raise DaemonUnavailable(_t("Druckdienst startet nicht. Log: {value}", value=paths.log_dir() / 'p12d.log'))


def daemon_running(*, connector: Callable[..., DaemonClient] = DaemonClient.connect,
                   timeout_s: float = 0.3) -> bool:
    """True, wenn ein Druckdienst für dieses App-Verzeichnis antwortet (verbinden + ping)."""
    return daemon_pid(connector=connector, timeout_s=timeout_s) is not None


def daemon_pid(*, connector: Callable[..., DaemonClient] = DaemonClient.connect,
               timeout_s: float = 0.3) -> int | None:
    """PID des antwortenden Druckdienstes oder None (jede Ausnahme heißt: läuft nicht)."""
    try:
        client = connector(client="cli", timeout_s=timeout_s)
    except Exception:  # noqa: BLE001
        return None
    try:
        result = client.call("ping", timeout=max(timeout_s, 1.0))
        return int(result.get("pid") or getattr(client, "server_pid", 0) or 0)
    except Exception:  # noqa: BLE001
        return None
    finally:
        try:
            client.close()
        except Exception:  # noqa: BLE001
            pass
