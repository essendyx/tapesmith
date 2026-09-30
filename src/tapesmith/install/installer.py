"""Installation ohne Adminrechte und ohne eigene EXE: `py -m tapesmith install`.

Unter `<Wurzel>` (Standard `%LOCALAPPDATA%\\Programs\\Tapesmith`) entsteht je Version eine eigene
Python-Umgebung `versions\\<v>` (`install.venv.provision`: venv, pip nur mit Wheels, Selbsttest),
die Junction `current` zeigt auf die aktive. Gestartet wird immer das signierte `pythonw.exe` der
Umgebung mit `-m`:

- Startmenü „Tapesmith“: `current\\Scripts\\pythonw.exe -m tapesmith.webui.browser`
- Autostart (HKCU Run „Tapesmith“): `… -m tapesmith.gui.tray`
- `tapesmith://`, `p12label://` und Kontextmenü: `… -m tapesmith.webui.browser …`
- Apps und Features mit Deinstallation: `… -m tapesmith uninstall`

Eine vorhandene Installation des früheren portablen Builds (PyInstaller, `versions\\<v>\\Tapesmith.exe`)
und ein Autostart aus einer Quellcode-Umgebung (z. B. `C:\\src\\tapesmith\\.venv`) werden beim
Installieren abgelöst. Benutzerdaten (`%APPDATA%\\Tapesmith`) bleiben immer unberührt.

`install()` berührt Registry und Startmenü nur über die übergebenen Backends (Standard `None`);
`main()` baut die echten Backends, außer mit `--no-registry`/`--no-shortcuts`. Das Ergebnis steht
auf der Konsole und in `<App-Verzeichnis>/logs/install.log`, der Exit-Code sagt ok (0) oder
Fehler (1)."""

from __future__ import annotations

import argparse
import functools
import json
import os
import shutil
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from tapesmith import launch
from tapesmith.install import junction, layout, processes
from tapesmith.install import venv as venv_mod
from tapesmith.i18n import _t

APP_MODULE = "tapesmith.webui.browser"
TRAY_MODULE = "tapesmith.gui.tray"
UNINSTALL_ARGS = "-m tapesmith uninstall"
ICON_RELATIVE = Path("Lib") / "site-packages" / "tapesmith" / "icons" / "app.ico"


@dataclass(frozen=True)
class InstallResult:
    root: Path
    version: str
    lines: list[str]


def _dir_size_kb(path: Path) -> int:
    total = 0
    for f in path.rglob("*"):
        try:
            if f.is_file():
                total += f.stat().st_size
        except OSError:
            continue
    return max(1, total // 1024)


def current_icon(root: Path) -> Path:
    """Programmsymbol der aktiven Version (über die Junction, bleibt bei Updates gültig)."""
    return layout.current_link(root) / ICON_RELATIVE


def _default_stopper(root: Path) -> bool:
    """Standard-`stopper`: Druckdienst über IPC beenden, übrige Prozesse unter `root` (außer
    dem eigenen und seinem Starter) hart beenden. `True`, wenn danach keine mehr laufen."""
    from tapesmith import config

    try:
        cfg = config.load_config()
    except Exception:  # noqa: BLE001 (eine kaputte Konfiguration darf die Installation nicht crashen)
        cfg = {}
    processes.stop_daemon(cfg)
    remaining = processes.processes_under(root, exclude_pids=processes.own_pids())
    if not remaining:
        return True
    left = processes.terminate([p.pid for p in remaining])
    return not left


def activate(version: str, *, root: Path | None = None, now: Callable | None = None) -> layout.InstallState:
    """Stellt die Junction `current` auf `version` um und schreibt `install.json` fort
    (`previous` = alte `current`, `versions` sortiert, `installed_at`)."""
    root = root if root is not None else layout.install_root()
    target = layout.version_dir(version, root)
    if not target.is_dir():
        raise ValueError(_t("Version nicht installiert: {version} ({target})", version=version, target=target))

    link = layout.current_link(root)
    state = layout.read_state(root) or layout.InstallState()
    # Neuinstallation derselben Version: die bisherige vorige Version bleibt (sonst zeigte
    # `previous` auf die aktive Version und die Rückstellung wäre verloren).
    previous = state.current if state.current != version else state.previous

    if junction.read_junction(link) is None:
        junction.create_junction(link, target)
    else:
        junction.switch_junction(link, target)

    versions = sorted(set(state.versions) | {version}, key=layout.parse_version)
    new_state = layout.InstallState(current=version, previous=previous, versions=versions,
                                    failed=[v for v in state.failed if v != version],
                                    installed_at=layout.now_iso(now), channel=state.channel,
                                    python=state.python)
    layout.write_state(new_state, root)
    return new_state


def remove_version(version: str, *, root: Path | None = None) -> None:
    """Löscht `versions\\<version>` vollständig. Nie die aktive Version (`ValueError`)."""
    root = root if root is not None else layout.install_root()
    state = layout.read_state(root)
    if state is not None and state.current == version:
        raise ValueError(_t("Aktive Version kann nicht entfernt werden: {version}", version=version))
    target = layout.version_dir(version, root)
    if target.exists():
        shutil.rmtree(target)
    if state is not None and (version in state.versions or version in state.failed):
        new_state = layout.InstallState(
            current=state.current, previous=state.previous if state.previous != version else None,
            versions=[v for v in state.versions if v != version],
            failed=[v for v in state.failed if v != version],
            installed_at=state.installed_at, channel=state.channel, python=state.python)
        layout.write_state(new_state, root)


def prune(keep: int, *, root: Path | None = None) -> list[str]:
    """Entfernt alte, inaktive Versionen: `failed`-Versionen immer zuerst (sie bestanden ihren
    Selbsttest nicht, kein Grund sie für einen Rückfall zu behalten); von den übrigen
    Versionen außer `current` bleiben die `keep` neuesten (das schließt `previous` praktisch
    immer ein, da sie stets die neueste inaktive Version ist). Gibt die entfernten Versionen
    zurück (`failed` zuerst, dann älteste zuerst)."""
    root = root if root is not None else layout.install_root()
    state = layout.read_state(root)
    if state is None:
        return []
    failed_set = set(state.failed)
    candidates = [v for v in state.versions if v != state.current]
    failed_candidates = sorted((v for v in candidates if v in failed_set), key=layout.parse_version)
    ok_candidates = sorted((v for v in candidates if v not in failed_set), key=layout.parse_version)
    to_keep = set(ok_candidates[-keep:]) if keep > 0 else set()
    to_remove = failed_candidates + [v for v in ok_candidates if v not in to_keep]
    removed = []
    for version in to_remove:
        remove_version(version, root=root)
        removed.append(version)
    return removed


def register_version(version: str, root: Path) -> layout.InstallState:
    """Trägt eine fertig bereitgestellte, noch nicht aktive Version in `install.json` ein."""
    state = layout.read_state(root) or layout.InstallState()
    versions = sorted(set(state.versions) | {version}, key=layout.parse_version)
    new_state = layout.InstallState(current=state.current, previous=state.previous, versions=versions,
                                    failed=[v for v in state.failed if v != version],
                                    installed_at=state.installed_at, channel=state.channel, python=state.python)
    layout.write_state(new_state, root)
    return new_state


def retire_frozen_versions(root: Path) -> list[str]:
    """Entfernt Versionsordner des früheren portablen Builds (`Tapesmith.exe` statt Python-Umgebung)
    und Reste des alten Updaters (`*.staging`, `downloads`). Die aktive Version muss vorher schon
    eine Python-Umgebung sein. Gibt Protokollzeilen zurück."""
    lines: list[str] = []
    versions_dir = root / "versions"
    state = layout.read_state(root)
    retired: list[str] = []
    if versions_dir.is_dir():
        for entry in sorted(versions_dir.iterdir()):
            if entry.name.endswith(".staging") and entry.is_dir():
                shutil.rmtree(entry, ignore_errors=True)
                continue
            if state is not None and entry.name == state.current:
                continue
            if entry.is_dir() and layout.is_frozen_version(entry):
                try:
                    shutil.rmtree(entry)
                except OSError as exc:
                    lines.append(_t("Alte portable Version {name} nicht entfernt: {exc}", name=entry.name, exc=exc))
                    continue
                retired.append(entry.name)
    downloads = root / "downloads"
    if downloads.is_dir():
        shutil.rmtree(downloads, ignore_errors=True)
    if retired and state is not None:
        layout.write_state(layout.InstallState(
            current=state.current, previous=state.previous if state.previous not in retired else None,
            versions=[v for v in state.versions if v not in retired],
            failed=[v for v in state.failed if v not in retired],
            installed_at=state.installed_at, channel=state.channel, python=state.python), root)
    if retired:
        lines.append(_t("Portable Version abgelöst: {items}", items=", ".join(retired)))
    return lines


def _stop_running(root: Path, stopper: Callable[[Path], bool] | None) -> None:
    running = processes.processes_under(root, exclude_pids=processes.own_pids())
    if running:
        stop = stopper or _default_stopper
        if not stop(root):
            raise RuntimeError(
                _t("Tapesmith läuft noch und lässt sich nicht beenden. Bitte Tapesmith manuell beenden und die Installation erneut versuchen."))


def install(*, version: str, root: Path | None = None, python: Path | None = None,
            spec: venv_mod.PipSpec | None = None, run: venv_mod.Runner = venv_mod.run_hidden,
            force: bool = False, shortcuts=None, uninstall_registry=None, registry=None,
            autostart: bool = True, start: bool = True, open_ui: bool = False,
            spawn: Callable[[Sequence[str]], int] | None = None,
            stopper: Callable[[Path], bool] | None = None, now: Callable | None = None,
            legacy_root: Path | None = None, legacy_menu_dir: Path | None = None,
            legacy_uninstall_registry=None, legacy_stopper: Callable[[Path], bool] | None = None,
            legacy_schedule_delete: Callable[[Path], None] | None = None,
            source_stopper: Callable[[Path], bool] | None = None,
            log: Callable[[str], None] | None = None) -> InstallResult:
    """Installiert Tapesmith `version` als eigene Python-Umgebung und schaltet sie aktiv.

    `python`: Basis-Python für die Umgebung (Standard: das laufende). `spec`: was pip installiert
    (Standard `tapesmith==<version>` von PyPI). Eine schon fertige Umgebung derselben Version wird
    ohne `force` wiederverwendet. `legacy_*`: Ablösung einer alten "P12 Label"-Installation;
    `source_stopper`: beendet Tapesmith aus einer Quellcode-Umgebung, auf die der alte Autostart
    zeigte (nur mit `registry`)."""
    root = root if root is not None else layout.install_root()
    python = Path(python) if python is not None else venv_mod.base_python()
    spec = spec or venv_mod.PipSpec(requirements=[f"tapesmith=={version}"])
    lines: list[str] = []
    say = log or (lambda _line: None)

    target = layout.version_dir(version, root)
    reuse = target.is_dir() and layout.is_complete_version(target) and not force
    if reuse:
        lines.append(_t("Version {version} ist schon bereitgestellt: {target}", version=version, target=target))
    else:
        if target.exists():
            # Belegter Ordner (früherer portabler Build gleicher Version, Rest eines Abbruchs oder
            # Neuinstallation mit --force): erst alles unter der Wurzel beenden.
            _stop_running(root, stopper)
        root.mkdir(parents=True, exist_ok=True)
        try:
            venv_mod.provision(root, version, python=python, spec=spec, run=run, log=say)
        except venv_mod.ProvisionError as exc:
            detail = f"\n{exc.output}" if exc.output else ""
            raise RuntimeError(f"{exc}{detail}") from exc
        lines.append(_t("Installiert: {version} nach {target_dir}", version=version, target_dir=target))

    _stop_running(root, stopper)
    state = activate(version, root=root, now=now)
    layout.write_state(layout.InstallState(current=state.current, previous=state.previous,
                                           versions=state.versions, failed=state.failed,
                                           installed_at=state.installed_at, channel=state.channel,
                                           python=str(python)), root)
    lines.extend(retire_frozen_versions(root))

    pythonw = layout.current_pythonw(root)
    icon = current_icon(root)

    if shortcuts is not None:
        from tapesmith.install import shortcuts as shortcuts_mod

        menu_dir = shortcuts_mod.start_menu_dir()
        shortcuts.create(menu_dir / "Tapesmith.lnk", pythonw, arguments=f"-m {APP_MODULE}", icon=icon,
                         workdir=root, description="Tapesmith")
        shortcuts.create(menu_dir / "Tapesmith deinstallieren.lnk", pythonw, arguments=UNINSTALL_ARGS,
                         icon=icon, workdir=root, description=_t("Tapesmith deinstallieren"))
        lines.append(_t("Startmenü: {menu_dir}", menu_dir=menu_dir))

    if uninstall_registry is not None:
        from tapesmith.install.registry import write_uninstall_entry

        write_uninstall_entry(uninstall_registry, root=root, version=version, size_kb=_dir_size_kb(target))
        lines.append(_t("Registry: Eintrag unter Installierte Apps"))

    if registry is not None:
        from tapesmith import integration as integration_mod
        from tapesmith.install import legacy

        source_env = legacy.source_run_env(registry, root)
        if source_env is not None:
            lines.extend(legacy.stop_source_run(source_env, stopper=source_stopper))
        pythonw_str = str(pythonw)
        parts = ("context", "uri") + (("autostart",) if autostart else ())
        reg_lines = integration_mod.install(
            registry, parts,
            command=functools.partial(launch.registry_command, executable=pythonw_str, frozen=False),
            icon=str(icon),
            autostart_argv=[pythonw_str, "-m", TRAY_MODULE] if autostart else None,
        )
        if not autostart:
            integration_mod.uninstall(registry, ("autostart",))
        if reg_lines:  # idempotent: eine unveränderte Zweitinstallation setzt nichts neu
            lines.append(_t("Registry: Kontextmenü, URI{value}", value=', Autostart' if autostart else ''))

    if legacy_root is not None or legacy_uninstall_registry is not None:
        from tapesmith.install import legacy

        lines.extend(legacy.remove_legacy(
            root=legacy_root, new_root=root, shortcuts=shortcuts, menu_dir=legacy_menu_dir,
            uninstall_registry=legacy_uninstall_registry, registry=registry,
            stopper=legacy_stopper, schedule_delete=legacy_schedule_delete))

    if start:
        spawner = spawn or launch.spawn_detached
        spawner([str(pythonw), "-m", TRAY_MODULE])
        lines.append(_t("Gestartet: Tapesmith (Tray)"))
        if open_ui:
            spawner([str(pythonw), "-m", APP_MODULE])
            lines.append(_t("Geöffnet: Web-Oberfläche im Standardbrowser"))

    lines.append(_t(r"Benutzerdaten bleiben in %APPDATA%\Tapesmith"))
    return InstallResult(root=root, version=version, lines=lines)


# ---------- `py -m tapesmith install` ----------

def add_arguments(p: argparse.ArgumentParser) -> None:
    p.add_argument("--root", type=Path, default=None, help=_t("Installationsordner (Standard: LOCALAPPDATA\\Programs\\Tapesmith)"))
    p.add_argument("--status", action="store_true", help=_t("Installationszustand anzeigen, nichts ändern"))
    p.add_argument("--json", action="store_true", help=_t("mit --status: als JSON ausgeben"))
    p.add_argument("--python", type=Path, default=None, help=_t("Basis-Python für die Umgebung (Standard: das laufende)"))
    p.add_argument("--wheel", type=Path, action="append", default=[],
                   help=_t("lokales Tapesmith-Wheel statt PyPI (mehrfach möglich)"))
    p.add_argument("--find-links", action="append", default=[], metavar=_t("ORDNER"),
                   help=_t("zusätzlicher Ordner mit Wheels (pip --find-links)"))
    p.add_argument("--no-index", action="store_true", help=_t("nur --find-links, kein PyPI"))
    p.add_argument("--index-url", default=None, help=_t("anderer Paketindex als PyPI"))
    p.add_argument("--lock", type=Path, default=None, help=_t("Lock-Liste mit SHA-256 (pip --require-hashes)"))
    p.add_argument("--force", action="store_true", help=_t("vorhandene Umgebung derselben Version neu anlegen"))
    p.add_argument("--no-shortcuts", action="store_true", help=_t("kein Startmenü"))
    p.add_argument("--no-registry", action="store_true", help=_t("keine Registry (Autostart, URI, Apps und Features)"))
    p.add_argument("--no-autostart", action="store_true", help=_t("kein Autostart"))
    p.add_argument("--no-start", action="store_true", help=_t("Tapesmith danach nicht starten"))
    p.add_argument("--no-open", action="store_true", help=_t("Web-Oberfläche nach der Installation nicht öffnen"))
    p.add_argument("--quiet", action="store_true", help=_t("still: wie --no-open"))


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m tapesmith install",
                                description=_t("Tapesmith installieren (ohne Adminrechte, ohne eigene EXE)"))
    add_arguments(p)
    return p


def _app_version() -> str:
    from tapesmith import __version__
    return __version__


def _log_result(text: str, ok: bool) -> None:
    """Ergebnis in `<App-Verzeichnis>/logs/install.log` anhängen."""
    from datetime import datetime

    from tapesmith import paths
    try:
        log = paths.log_dir() / "install.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {'OK' if ok else 'FEHLER'} {_app_version()}\n{text}\n")
    except OSError:
        pass


def _echo(text: str, *, err: bool = False) -> None:
    stream = sys.stderr if err else sys.stdout
    if stream is None:
        return
    try:
        print(text, file=stream, flush=True)
    except (OSError, ValueError):
        pass


def spec_from_args(args: argparse.Namespace, version: str) -> venv_mod.PipSpec:
    requirements = [str(Path(w).resolve()) for w in args.wheel] or [f"tapesmith=={version}"]
    return venv_mod.PipSpec(requirements=requirements, lock_file=args.lock,
                            find_links=[str(Path(f).resolve()) if Path(f).exists() else str(f) for f in args.find_links],
                            no_index=args.no_index, index_url=args.index_url)


def status_text(data: dict) -> list[str]:
    if not data.get("installed"):
        return [data.get("error") or _t("nicht installiert ({root})", root=data.get("root") or "-")]
    return [
        _t("Wurzel: {root}", root=data["root"]),
        _t("Aktiv: {current} (vorige: {value})", current=data["current"], value=data["previous"] or "-"),
        _t("Versionen: {value}", value=", ".join(data["versions"]) or "-"),
        _t("Junction current: {value}", value=data["current_target"] or "-"),
        _t("Python: {value}", value=data.get("python") or "-"),
        _t("Art: {value}", value=data.get("kind") or "-"),
    ]


def status_dict(root: Path | None = None) -> dict:
    """Nur lesend: Wurzel, Versionen, Junction, Art (Python-Umgebung oder portabler Build)."""
    try:
        root = root if root is not None else layout.install_root()
    except RuntimeError as exc:
        return {"installed": False, "error": str(exc)}
    state = layout.read_state(root)
    if state is None:
        return {"installed": False, "root": str(root)}
    target = junction.read_junction(layout.current_link(root))
    kind = None
    if state.current:
        vdir = layout.version_dir(state.current, root)
        kind = "python" if layout.is_venv_version(vdir) else ("portable" if layout.is_frozen_version(vdir) else None)
    return {
        "installed": True,
        "root": str(root),
        "current": state.current,
        "previous": state.previous,
        "versions": list(state.versions),
        "failed": list(state.failed),
        "current_target": str(target) if target is not None else None,
        "installed_at": state.installed_at,
        "channel": state.channel,
        "python": state.python,
        "kind": kind,
    }


def run_args(args: argparse.Namespace, *, run: venv_mod.Runner = venv_mod.run_hidden) -> int:
    if args.status:
        data = status_dict(args.root)
        if args.json:
            _echo(json.dumps(data, ensure_ascii=False))
        else:
            for line in status_text(data):
                _echo(line)
        return 0

    from tapesmith.install import legacy

    shortcuts = None
    uninstall_registry = None
    registry = None
    legacy_uninstall_registry = None
    legacy_menu_dir = None
    if not args.no_shortcuts:
        from tapesmith.install.shortcuts import PowerShellShortcuts, start_menu_dir
        shortcuts = PowerShellShortcuts()
        legacy_menu_dir = start_menu_dir().parent / legacy.LEGACY_START_MENU_NAME
    if not args.no_registry:
        from tapesmith.install.registry import UninstallRegistry
        from tapesmith.integration import WinRegBackend
        uninstall_registry = UninstallRegistry()
        legacy_uninstall_registry = UninstallRegistry(legacy.LEGACY_UNINSTALL_KEY)
        registry = WinRegBackend()

    version = _app_version()
    ok = True
    try:
        result = install(version=version, root=args.root, python=args.python, spec=spec_from_args(args, version),
                         run=run, force=args.force, shortcuts=shortcuts,
                         uninstall_registry=uninstall_registry, registry=registry,
                         autostart=not args.no_autostart, start=not args.no_start,
                         open_ui=not (args.no_open or args.quiet),
                         legacy_root=legacy.default_root(), legacy_menu_dir=legacy_menu_dir,
                         legacy_uninstall_registry=legacy_uninstall_registry, log=_echo)
        text = "\n".join(result.lines)
    except (ValueError, RuntimeError, OSError) as exc:
        text = _t("Installation fehlgeschlagen: {exc}", exc=exc)
        ok = False
    except Exception as exc:  # noqa: BLE001: ohne Konsole (pythonw) darf nichts stumm scheitern
        text = _t("Installation fehlgeschlagen: {name}: {exc}", name=type(exc).__name__, exc=exc)
        ok = False
    _log_result(text, ok)
    _echo(text, err=not ok)
    return 0 if ok else 1


def main(argv: list[str] | None = None, *, run: venv_mod.Runner = venv_mod.run_hidden) -> int:
    """`python -m tapesmith install …`: Ergebnis auf der Konsole, im Log und als Exit-Code."""
    return run_args(_parser().parse_args(argv), run=run)
