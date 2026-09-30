"""Update anwenden: `pythonw -m tapesmith.update.apply --version V [--root D]
[--reopen-route R] [--rollback] [--no-tray]`. `--no-tray` bzw. `TAPESMITH_NO_TRAY=1` startet nach dem
Umschalten nur den Druckdienst (Rechner ohne Anmeldung, Probeläufe).

Läuft losgelöst aus dem echten Ordner der **alten** Version (`versions\\<alt>\\Scripts\\pythonw.exe`,
nie über `current`), damit das Umstellen der Junction den laufenden Updater nicht berührt. Ablauf:
Mutex `Local\\Tapesmith.Update`, Druckdienst über IPC `shutdown` beenden (nicht erzwungen;
belegt: bis 60 s warten, sonst Abbruch `busy`), übrige Prozesse unter der Wurzel beenden (außer
dem eigenen und seinem Starter), `activate(V)`, Druckdienst und Tray aus `current` starten
(`pythonw -m tapesmith.daemon` bzw. `tapesmith.gui.tray`), `/health` muss binnen 60 s
`version == V` melden. Sonst Rückfall auf die alte Version, `V` landet in `install.json` `failed`.
Erfolg: `prune(keep_versions)`, Oberfläche im Browser wieder öffnen.

Jeder Schritt schreibt den Zustand (`installing`, `idle`, `failed`) nach `state.json`. Qt-frei."""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from tapesmith import launch
from tapesmith.errors import EXIT_BUSY, EXIT_ERROR, EXIT_OK
from tapesmith.install import installer, layout, processes
from tapesmith.update import state as state_mod
from tapesmith.update.errors import UpdateError
from tapesmith.i18n import _t

log = logging.getLogger("tapesmith.update")

MUTEX_NAME = "Local\\Tapesmith.Update"
BUSY_WAIT_S = 60.0
BUSY_RETRY_S = 5.0
HEALTH_TIMEOUT_S = 60.0
HEALTH_INTERVAL_S = 0.5
DEFAULT_KEEP = 2

RESULT_OK = "ok"
RESULT_ROLLED_BACK = "rolled_back"
RESULT_BUSY = "busy"


# ---------- Standard-Abhängigkeiten (Tests ersetzen alle) ----------

def _load_config() -> dict:
    from tapesmith import config

    try:
        return config.load_config()
    except Exception:  # noqa: BLE001 (eine kaputte Konfiguration darf das Update nicht verhindern)
        return {}


def _default_stopper() -> bool:
    return processes.stop_daemon(_load_config())


def _default_health() -> dict | None:
    from tapesmith.webapi.session import read_session
    from tapesmith.webui.browser import check_health

    session = read_session()
    if not session or not isinstance(session.get("port"), int):
        return None
    return check_health(session["port"])


def _default_keep() -> int:
    from tapesmith.config import setting

    try:
        return int(setting(_load_config(), "update.keep_versions"))
    except Exception:  # noqa: BLE001
        return DEFAULT_KEEP


# ---------- Zustand ----------

def _save(state: str, error: UpdateError | None = None, *, version: str | None = None) -> None:
    try:
        status = state_mod.load_status() or state_mod.UpdateStatus()
        status.state = state
        status.error = {"code": error.code, "message": str(error)} if error is not None else None
        if version is not None and state == "idle":
            status.current = version
            if status.available and status.available.get("version") == version:
                status.available = None
        state_mod.save_status(status)
    except Exception as exc:  # noqa: BLE001 (Zustand ist Anzeige, kein Grund abzubrechen)
        log.warning("Update-Zustand nicht schreibbar: %s", exc)


# ---------- Ablauf ----------

def _stop_others(root: Path, lister, killer) -> list[int]:
    procs = processes.processes_under(root, lister=lister, exclude_pids=processes.own_pids())
    if not procs:
        return []
    return processes.terminate([p.pid for p in procs], killer=killer)


def _start(root: Path, spawn: Callable[[Sequence[str]], int], *, tray: bool = True) -> None:
    kinds = ("daemon", "tray") if tray else ("daemon",)
    pythonw = str(layout.current_pythonw(root))
    for kind in kinds:
        try:
            spawn(launch.app_argv(kind, frozen=False, executable=pythonw))
        except Exception as exc:  # noqa: BLE001
            log.error("Start %s fehlgeschlagen: %s", kind, exc)


def _reopen(root: Path, route: str | None, spawn) -> None:
    """Oberfläche nach dem Umschalten auf `route` im Standardbrowser öffnen
    (`pythonw -m tapesmith.webui.browser --route R` öffnet einen Browser-Tab und beendet sich)."""
    if not route:
        return
    try:
        spawn(launch.app_argv("app", "--route", route, frozen=False, executable=str(layout.current_pythonw(root))))
    except Exception as exc:  # noqa: BLE001
        log.warning("Oberfläche nicht wieder im Browser geöffnet: %s", exc)


def _wait_healthy(version: str, health, clock, sleep) -> bool:
    deadline = clock() + HEALTH_TIMEOUT_S
    while True:
        try:
            info = health()
        except Exception:  # noqa: BLE001
            info = None
        if isinstance(info, dict) and info.get("version") == version:
            return True
        if clock() >= deadline:
            return False
        sleep(HEALTH_INTERVAL_S)


def _mark_failed(root: Path, version: str, previous: str | None) -> None:
    st = layout.read_state(root)
    if st is None:
        return
    failed = list(st.failed) + ([version] if version not in st.failed else [])
    layout.write_state(layout.InstallState(current=st.current, previous=previous, versions=list(st.versions),
                                           failed=failed, installed_at=st.installed_at, channel=st.channel), root)


def _restore_previous(root: Path, previous: str | None) -> None:
    st = layout.read_state(root)
    if st is None:
        return
    layout.write_state(layout.InstallState(current=st.current, previous=previous, versions=list(st.versions),
                                           failed=list(st.failed), installed_at=st.installed_at,
                                           channel=st.channel), root)


def apply_update(version: str | None, *, root: Path, reopen_route: str | None = None, rollback: bool = False,
                 stopper: Callable[[], bool] = _default_stopper,
                 lister: Callable[[], list] = processes.list_processes,
                 killer: Callable[[int, float], bool] | None = None,
                 spawn: Callable[[Sequence[str]], int] = launch.spawn_detached,
                 health: Callable[[], dict | None] = _default_health,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep,
                 keep: int | None = None,
                 pruner: Callable[..., list[str]] = installer.prune,
                 tray: bool = True) -> str:
    """Stellt auf `version` um (bzw. mit `rollback` auf `previous`). Ergebnis `ok`, `rolled_back`, `busy`."""
    root = Path(root)
    st = layout.read_state(root)
    if st is None or st.current is None:
        raise UpdateError("update.not_installed", _t("Keine Installation unter {root}", root=root))
    old = st.current
    old_previous = st.previous
    if rollback:
        version = st.previous
        if not version:
            raise UpdateError("update.apply_failed", _t("Keine vorige Version zum Zurückstellen vorhanden"))
    if not version:
        raise UpdateError("update.apply_failed", _t("Keine Zielversion angegeben"))
    if not layout.version_dir(version, root).is_dir():
        raise UpdateError("update.apply_failed", _t("Version {version} ist nicht bereitgestellt", version=version))
    if version == old:
        _save("idle", version=version)
        return RESULT_OK

    _save("installing")
    log.info("Update: %s -> %s%s", old, version, " (Rückstellung)" if rollback else "")

    deadline = clock() + BUSY_WAIT_S
    while not stopper():
        if clock() >= deadline:
            err = UpdateError("update.busy", _t("Druckdienst ist belegt, Update abgebrochen"))
            _save("idle" if rollback else "ready", err)
            log.info("Update abgebrochen: Druckdienst belegt")
            return RESULT_BUSY
        sleep(BUSY_RETRY_S)

    try:
        left = _stop_others(root, lister, killer)
    except Exception as exc:  # noqa: BLE001 (der Druckdienst ist schon beendet: alte Version wieder starten)
        log.error("Prozesse unter %s nicht ermittelbar: %s", root, exc)
        left = [-1]
    if left:
        log.error("Prozesse ließen sich nicht beenden: %s", left)
        _start(root, spawn, tray=tray)
        _save("failed", UpdateError("update.apply_failed",
                                    _t("Tapesmith ließ sich nicht vollständig beenden, Update abgebrochen")))
        _reopen(root, reopen_route, spawn)
        return RESULT_ROLLED_BACK

    switched = False
    try:
        installer.activate(version, root=root)
        switched = True
        _start(root, spawn, tray=tray)
        healthy = _wait_healthy(version, health, clock, sleep)
    except Exception as exc:  # noqa: BLE001 (jeder Fehler führt zum Rückfall)
        log.error("Umschalten auf %s fehlgeschlagen: %s", version, exc)
        healthy = False

    if healthy:
        try:
            pruner(keep if keep is not None else _default_keep(), root=root)
        except Exception as exc:  # noqa: BLE001
            log.warning("Alte Versionen nicht entfernt: %s", exc)
        _save("idle", version=version)
        _reopen(root, reopen_route, spawn)
        log.info("Update auf %s erfolgreich", version)
        return RESULT_OK

    log.error("Neue Version %s meldet sich nicht gesund, Rückfall auf %s", version, old)
    if switched:
        _stop_others(root, lister, killer)
    try:
        installer.activate(old, root=root)
    except Exception as exc:  # noqa: BLE001
        log.error("Rückfall auf %s fehlgeschlagen: %s", old, exc)
    if rollback:
        _restore_previous(root, old_previous)
    else:
        _mark_failed(root, version, old_previous)
    _start(root, spawn, tray=tray)
    _save("failed", UpdateError("update.apply_failed",
                                _t("Version {version} startete nicht fehlerfrei, zurück auf {old}", version=version, old=old)))
    _reopen(root, reopen_route, spawn)
    return RESULT_ROLLED_BACK


# ---------- `pythonw -m tapesmith.update.apply` ----------

def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m tapesmith.update.apply", add_help=False)
    p.add_argument("--version", default=None)
    p.add_argument("--root", type=Path, default=None)
    p.add_argument("--reopen-route", default=None)
    p.add_argument("--rollback", action="store_true")
    # Ohne Tray (nur Druckdienst): Server ohne Anmeldung, automatisierte Prüfläufe.
    p.add_argument("--no-tray", action="store_true")
    return p


def _setup_logging() -> None:
    try:
        from tapesmith import paths

        handler = logging.FileHandler(paths.log_dir() / "update.log", encoding="utf-8")
    except Exception:  # noqa: BLE001
        return
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)


def main(argv: list[str] | None = None, *, mutex_factory: Callable[[str], object] | None = None,
         **deps) -> int:
    """Einstieg für `pythonw -m tapesmith.update.apply …`. Läuft schon ein Update (Mutex belegt): Exit 0."""
    args = _parser().parse_args(argv)
    if not args.rollback and not args.version:
        return EXIT_ERROR
    if mutex_factory is None:
        from tapesmith.daemon.instance import SingleInstance

        mutex_factory = SingleInstance
    mutex = mutex_factory(MUTEX_NAME)
    if not mutex.acquire():
        return EXIT_OK
    if not deps:
        _setup_logging()
    try:
        root = args.root if args.root is not None else layout.install_root()
        result = apply_update(args.version, root=root, reopen_route=args.reopen_route, rollback=args.rollback,
                              tray=not (args.no_tray or os.environ.get("TAPESMITH_NO_TRAY") == "1"), **deps)
    except UpdateError as exc:
        log.error("Update fehlgeschlagen: %s", exc)
        _save("failed", exc)
        return EXIT_ERROR
    except Exception as exc:  # noqa: BLE001 (Zustand nie auf "installing" stehen lassen)
        log.exception("Update: unerwarteter Fehler")
        _save("failed", UpdateError("update.apply_failed", _t("Update fehlgeschlagen ({name})", name=type(exc).__name__)))
        return EXIT_ERROR
    finally:
        mutex.release()
    return {RESULT_OK: EXIT_OK, RESULT_BUSY: EXIT_BUSY}.get(result, EXIT_ERROR)


if __name__ == "__main__":
    sys.exit(main())
