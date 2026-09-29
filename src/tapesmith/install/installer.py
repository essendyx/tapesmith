"""Installation ohne Adminrechte: Kopieren nach `versions\\<v>`, Junction
`current` umstellen, Startmenü, Apps-&-Features-Eintrag, Kontextmenü/URI/Autostart, Start.

Kein Meldungsfenster: das Ergebnis steht in `<App-Verzeichnis>/logs/install.log`, der Exit-Code
sagt ok (0) oder Fehler (1). Nach erfolgreicher Installation starten Tray und Web-Oberfläche
(Standardbrowser), außer mit `--no-start` bzw. `--no-open`/`--quiet`.

`install()` selbst berührt keine Registry und kein Startmenü, solange die Backend-Parameter
`None` bleiben (Standard): nur `installer.main()` (EXE-Weiche `Tapesmith.exe --install`)
konstruiert die echten Backends (`WScriptShortcuts`, `UninstallRegistry`, `WinRegBackend`)."""

from __future__ import annotations

import argparse
import functools
import os
import shutil
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from tapesmith import launch
from tapesmith.install import junction, layout, processes
from tapesmith.i18n import _t

@dataclass(frozen=True)
class InstallResult:
    root: Path
    version: str
    lines: list[str]


def _dir_size_kb(path: Path) -> int:
    total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return max(1, total // 1024)


def _copy_version(source_dir: Path, target_dir: Path) -> None:
    staging = target_dir.parent / f"{target_dir.name}.staging"
    if staging.exists():
        shutil.rmtree(staging)
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_dir, staging)
    os.replace(staging, target_dir)


def _default_stopper(root: Path) -> bool:
    """Standard-`stopper`: Druckdienst über IPC beenden, übrige Prozesse unter `root` (außer
    dem eigenen) hart beenden. `True`, wenn danach keine Prozesse mehr unter `root` laufen."""
    from tapesmith import config

    try:
        cfg = config.load_config()
    except Exception:  # noqa: BLE001 (eine kaputte Konfiguration darf die Installation nicht crashen)
        cfg = {}
    processes.stop_daemon(cfg)
    remaining = processes.processes_under(root, exclude_pids=(os.getpid(),))
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
                                    failed=list(state.failed), installed_at=layout.now_iso(now),
                                    channel=state.channel)
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
            current=state.current, previous=state.previous,
            versions=[v for v in state.versions if v != version],
            failed=[v for v in state.failed if v != version],
            installed_at=state.installed_at, channel=state.channel)
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


def install(source_dir: Path, *, version: str, root: Path | None = None, shortcuts=None,
           uninstall_registry=None, registry=None, integrate: bool = True, autostart: bool = True,
           start: bool = True, open_ui: bool = False,
           spawn: Callable[[Sequence[str]], int] | None = None,
           stopper: Callable[[Path], bool] | None = None, now: Callable | None = None,
           legacy_root: Path | None = None, legacy_menu_dir: Path | None = None,
           legacy_uninstall_registry=None, legacy_stopper: Callable[[Path], bool] | None = None,
           legacy_schedule_delete: Callable[[Path], None] | None = None) -> InstallResult:
    """Installiert `source_dir` (muss `Tapesmith.exe` enthalten) als `version`. Ohne die
    Backend-Parameter (`shortcuts`/`uninstall_registry`/`registry`, alle Standard `None`)
    bleiben Startmenü und Registry unberührt: `installer.main()` übergibt die echten Backends.

    `legacy_*`: Ablösung einer alten "P12 Label"-Installation (`install.legacy`), erst nach der
    erfolgreichen Installation und vor dem Start. Ohne `legacy_root` bleibt sie aus."""
    source_dir = Path(source_dir)
    exe = source_dir / layout.APP_EXE
    if not exe.is_file():
        raise ValueError(_t("Keine Tapesmith.exe in {source_dir}", source_dir=source_dir))

    root = root if root is not None else layout.install_root()
    lines: list[str] = []

    existing_state = layout.read_state(root)
    if existing_state is not None and existing_state.current is not None:
        running = processes.processes_under(root, exclude_pids=(os.getpid(),))
        if running:
            stop = stopper or _default_stopper
            if not stop(root):
                raise RuntimeError(
                    _t("Tapesmith läuft noch und lässt sich nicht beenden. Bitte Tapesmith manuell beenden und die Installation erneut versuchen."))

    target_dir = layout.version_dir(version, root)
    source_resolved = os.path.normpath(str(source_dir.resolve())).upper()
    target_resolved = os.path.normpath(str(target_dir.resolve())).upper() if target_dir.exists() else None

    if target_resolved is not None and source_resolved == target_resolved:
        pass  # Neuinstallation aus dem installierten Ordner heraus: nichts zu kopieren
    elif target_dir.exists():
        # Auch bei gleicher Versionsnummer ersetzen: ein neuer Build darf nie stillschweigend
        # ignoriert werden. Laufende Prozesse sind oben schon beendet.
        shutil.rmtree(target_dir)
        _copy_version(source_dir, target_dir)
    else:
        _copy_version(source_dir, target_dir)

    lines.append(_t("Installiert: {version} nach {target_dir}", version=version, target_dir=target_dir))

    activate(version, root=root, now=now)

    if shortcuts is not None:
        from tapesmith.install import shortcuts as shortcuts_mod

        menu_dir = shortcuts_mod.start_menu_dir()
        exe_path = layout.current_exe(root)
        shortcuts.create(menu_dir / "Tapesmith.lnk", exe_path, description="Tapesmith")
        shortcuts.create(menu_dir / "Tapesmith deinstallieren.lnk", exe_path, arguments="--uninstall",
                         description="Tapesmith deinstallieren")
        lines.append(_t("Startmenü: {menu_dir}", menu_dir=menu_dir))

    if uninstall_registry is not None:
        from tapesmith.install.registry import write_uninstall_entry

        write_uninstall_entry(uninstall_registry, root=root, version=version,
                              size_kb=_dir_size_kb(target_dir))
        lines.append(_t("Registry: Eintrag unter Installierte Apps"))

    if registry is not None:
        from tapesmith import integration as integration_mod

        exe_str = str(layout.current_exe(root))
        parts = ("context", "uri") + (("autostart",) if autostart else ())
        reg_lines = integration_mod.install(
            registry, parts,
            command=functools.partial(launch.registry_command, executable=exe_str, frozen=True),
            icon=exe_str,
            autostart_argv=[exe_str, "--tray"] if autostart else None,
        )
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
        spawner([str(layout.current_exe(root)), "--tray"])
        lines.append(_t("Gestartet: Tapesmith (Tray)"))
        if open_ui:
            spawner([str(layout.current_exe(root)), "--app"])
            lines.append(_t("Geöffnet: Web-Oberfläche im Standardbrowser"))

    lines.append(_t(r"Benutzerdaten bleiben in %APPDATA%\Tapesmith"))
    return InstallResult(root=root, version=version, lines=lines)


# ---------- EXE-Weiche `Tapesmith.exe --install` ----------

def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="Tapesmith --install", add_help=False)
    p.add_argument("--root", type=Path, default=None)
    p.add_argument("--no-shortcuts", action="store_true")
    p.add_argument("--no-registry", action="store_true")
    p.add_argument("--no-autostart", action="store_true")
    p.add_argument("--no-start", action="store_true")
    p.add_argument("--no-open", action="store_true", help=_t("Web-Oberfläche nach der Installation nicht öffnen"))
    p.add_argument("--quiet", action="store_true", help=_t("still: wie --no-open"))
    return p


def _app_version() -> str:
    from tapesmith import __version__
    return __version__


def _default_source_dir() -> Path:
    """Ordner der gerade laufenden EXE (der portable Build, aus dem `--install` gestartet
    wurde). In Entwicklung/Tests immer über `source_dir=` überschreiben."""
    return Path(sys.executable).resolve().parent


def _log_result(text: str, ok: bool) -> None:
    """Ergebnis in `<App-Verzeichnis>/logs/install.log` anhängen (einziger Ergebnisbericht)."""
    from datetime import datetime

    from tapesmith import paths
    try:
        log = paths.log_dir() / "install.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {'OK' if ok else 'FEHLER'} {_app_version()}\n{text}\n")
    except OSError:
        pass


def main(argv: list[str] | None = None, *, source_dir: Path | None = None) -> int:
    """`Tapesmith.exe --install`: Ergebnis nur ins Log (`install.log`) und als Exit-Code."""
    args = _parser().parse_args(argv)
    src = source_dir if source_dir is not None else _default_source_dir()

    from tapesmith.install import legacy

    shortcuts = None
    uninstall_registry = None
    registry = None
    legacy_uninstall_registry = None
    legacy_menu_dir = None
    if not args.no_shortcuts:
        from tapesmith.install.shortcuts import WScriptShortcuts, start_menu_dir
        shortcuts = WScriptShortcuts()
        legacy_menu_dir = start_menu_dir().parent / legacy.LEGACY_START_MENU_NAME
    if not args.no_registry:
        from tapesmith.install.registry import UninstallRegistry
        from tapesmith.integration import WinRegBackend
        uninstall_registry = UninstallRegistry()
        legacy_uninstall_registry = UninstallRegistry(legacy.LEGACY_UNINSTALL_KEY)
        registry = WinRegBackend()

    ok = True
    try:
        result = install(src, version=_app_version(), root=args.root, shortcuts=shortcuts,
                         uninstall_registry=uninstall_registry, registry=registry,
                         autostart=not args.no_autostart, start=not args.no_start,
                         open_ui=not (args.no_open or args.quiet),
                         legacy_root=legacy.default_root(), legacy_menu_dir=legacy_menu_dir,
                         legacy_uninstall_registry=legacy_uninstall_registry)
        text = "\n".join(result.lines)
    except (ValueError, RuntimeError, OSError) as exc:
        text = _t("Installation fehlgeschlagen: {exc}", exc=exc)
        ok = False
    except Exception as exc:  # noqa: BLE001: die EXE ohne Konsole darf nie stumm scheitern
        text = _t("Installation fehlgeschlagen: {name}: {exc}", name=type(exc).__name__, exc=exc)
        ok = False
    _log_result(text, ok)
    if sys.stderr is not None:
        print(text, file=sys.stderr if not ok else sys.stdout)
    return 0 if ok else 1
