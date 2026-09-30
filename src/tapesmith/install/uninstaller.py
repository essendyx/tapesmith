"""Deinstallation ohne Adminrechte: Prozesse stoppen, Verknüpfungen und
Registry-Einträge entfernen, Junction `current` entfernen, Restordner per losgelöstem Prozess
löschen (der laufende Python-Prozess der aktiven Version kann seinen eigenen Ordner nicht
selbst löschen). Aufruf: `pythonw -m tapesmith uninstall` (Apps und Features, Startmenü) bzw.
`py -m tapesmith uninstall`. Benutzerdaten unter
%APPDATA%\\Tapesmith werden nie angefasst. Kein Meldungsfenster: das Ergebnis steht in
`<App-Verzeichnis>/logs/uninstall.log`, der Exit-Code sagt ok (0) oder Fehler (1)."""

from __future__ import annotations

import argparse
import os
import sys
import subprocess
from collections.abc import Callable
from pathlib import Path

from tapesmith import launch
from tapesmith.install import junction, layout, processes
from tapesmith.install.installer import _default_stopper
from tapesmith.i18n import _t

DELETE_WAIT_S = 3

# Umgebungsvariablen mit Ordnern, die die Deinstallation nie (auch nicht als Unterordner der
# Wurzel) löschen darf.
_PROTECTED_ENV = ("USERPROFILE", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "PROGRAMFILES",
                  "PROGRAMFILES(X86)", "SYSTEMROOT", "WINDIR")


def _real(path: Path | str) -> str:
    return os.path.normcase(os.path.realpath(os.path.abspath(str(path)))).rstrip("\\/")


def _inside(child: str, parent: str) -> bool:
    """`child` liegt in `parent` oder ist gleich (beide über `_real` normalisiert)."""
    return child == parent or child.startswith(parent + os.sep)


def _user_data_dirs() -> list[str]:
    dirs = []
    home = os.environ.get("TAPESMITH_HOME")
    if home:
        dirs.append(_real(home))
    appdata = os.environ.get("APPDATA")
    if appdata:
        dirs.append(_real(Path(appdata) / "Tapesmith"))
    return dirs


def check_root(root: Path) -> None:
    """Sicherheitsnetz vor dem rekursiven Löschen: `root` muss eine Tapesmith-Installation sein
    (`install.json` oder `versions`), darf keine Laufwerks- bzw. Freigabewurzel sein, weder die
    Benutzerdaten (`%APPDATA%\\Tapesmith`, `TAPESMITH_HOME`) enthalten noch in ihnen liegen und
    keinen Systemordner (Profil, AppData, Programme, Windows) enthalten. Sonst `ValueError`."""
    real = _real(root)
    if Path(real).parent == Path(real) or Path(real) == Path(Path(real).anchor):
        raise ValueError(_t("Deinstallation verweigert: {root} ist eine Laufwerkswurzel", root=root))
    for data in _user_data_dirs():
        if _inside(data, real) or _inside(real, data):
            raise ValueError(_t("Deinstallation verweigert: {root} überschneidet sich mit den Benutzerdaten ({data})", root=root, data=data))
    protected = [os.environ.get(name) for name in _PROTECTED_ENV]
    protected.append(str(Path.home()))
    for folder in filter(None, protected):
        if _inside(_real(folder), real):
            raise ValueError(_t("Deinstallation verweigert: {root} enthält den Systemordner {folder}", root=root, folder=folder))
    if not (Path(root) / "install.json").is_file() and not (Path(root) / "versions").is_dir():
        raise ValueError(_t("Deinstallation verweigert: in {root} liegt keine Tapesmith-Installation (install.json fehlt)", root=root))


def delete_command(root: Path, *, wait_s: int = DELETE_WAIT_S) -> str:
    """Fertige Befehlszeile für cmd.exe: `wait_s` Sekunden warten, dann `root` ganz löschen.

    Bewusst ein String statt einer argv-Liste: `subprocess` quotiert Listen für die C-Laufzeit
    (innere Anführungszeichen als Backslash plus Anführungszeichen), cmd.exe versteht das nicht
    und fand den Ordner nie (Probedeinstallation). Mit `/s` entfernt cmd nur das äußere
    Paar Anführungszeichen, der Pfad darf Leerzeichen enthalten."""
    return f'cmd.exe /d /s /c "ping -n {int(wait_s) + 1} 127.0.0.1 >nul & rmdir /s /q "{root}""'


def _default_schedule_delete(root: Path, *, spawn: Callable | None = None) -> None:
    """Startet losgelöst `ping … & rmdir /s /q "<root>"`: wartet kurz, bis dieser Prozess (der
    gerade aus `root` läuft) beendet ist, und löscht dann den ganzen Ordner."""
    command = delete_command(root)
    if spawn is not None:
        spawn(command)
        return

    def popen(_argv, **kwargs):
        return subprocess.Popen(command, **kwargs)

    launch.spawn_detached(["cmd.exe"], popen=popen)


def uninstall(*, root: Path | None = None, shortcuts=None, uninstall_registry=None, registry=None,
             stopper: Callable[[Path], bool] | None = None,
             schedule_delete: Callable[[Path], None] | None = None, quiet: bool = False) -> list[str]:
    """Deinstalliert die App unter `root`. Ohne Backend-Parameter (Standard `None`) bleiben
    Startmenü und Registry unberührt: `uninstaller.main()` übergibt die echten Backends."""
    root = root if root is not None else layout.install_root()
    check_root(root)
    lines: list[str] = []

    running = processes.processes_under(root, exclude_pids=processes.own_pids())
    if running:
        stop = stopper or _default_stopper
        if not stop(root):
            raise RuntimeError(_t("Tapesmith läuft noch und lässt sich nicht beenden. Bitte Tapesmith manuell beenden und die Deinstallation erneut versuchen."))

    if shortcuts is not None:
        from tapesmith.install.shortcuts import start_menu_dir

        menu_dir = start_menu_dir()
        removed_any = False
        for name in ("Tapesmith.lnk", "Tapesmith deinstallieren.lnk"):
            path = menu_dir / name
            if shortcuts.exists(path):
                shortcuts.delete(path)
                removed_any = True
        try:
            menu_dir.rmdir()  # nur, wenn leer (fremde Dateien bleiben)
        except OSError:
            pass
        if removed_any:
            lines.append(_t("Startmenü entfernt: {menu_dir}", menu_dir=menu_dir))

    if registry is not None:
        from tapesmith import integration as integration_mod

        removed = integration_mod.uninstall(registry, integration_mod.PARTS)
        if removed:
            lines.append(_t("Registry: Kontextmenü, URI und Autostart entfernt"))

    if uninstall_registry is not None:
        from tapesmith.install.registry import remove_uninstall_entry

        remove_uninstall_entry(uninstall_registry)
        lines.append(_t("Registry: Eintrag unter Installierte Apps entfernt"))

    link = layout.current_link(root)
    if junction.read_junction(link) is not None:
        os.rmdir(link)
        lines.append(_t("Verknüpfung entfernt: {link}", link=link))

    deleter = schedule_delete or _default_schedule_delete
    deleter(root)
    lines.append(_t("Programmordner wird entfernt: {root}", root=root))
    lines.append(_t(r"Benutzerdaten in %APPDATA%\Tapesmith bleiben erhalten"))
    return lines


# ---------- `python -m tapesmith uninstall` ----------

def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m tapesmith uninstall",
                                description=_t("Tapesmith deinstallieren (Benutzerdaten bleiben erhalten)"))
    p.add_argument("--root", type=Path, default=None)
    p.add_argument("--no-shortcuts", action="store_true")
    p.add_argument("--no-registry", action="store_true")
    p.add_argument("--quiet", action="store_true")
    return p


def _log_result(text: str, ok: bool) -> None:
    """Ergebnis in `<App-Verzeichnis>/logs/uninstall.log` anhängen (einziger Ergebnisbericht)."""
    from datetime import datetime

    from tapesmith import __version__, paths
    try:
        log = paths.log_dir() / "uninstall.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {'OK' if ok else 'FEHLER'} {__version__}\n{text}\n")
    except OSError:
        pass


def main(argv: list[str] | None = None, *, schedule_delete: Callable[[Path], None] | None = None) -> int:
    """`schedule_delete` ist nur zum Testen gedacht (Standard: echter losgelöster Prozess, der
    den Programmordner löscht, siehe `_default_schedule_delete`)."""
    args = _parser().parse_args(argv)

    shortcuts = None
    uninstall_registry = None
    registry = None
    if not args.no_shortcuts:
        from tapesmith.install.shortcuts import PowerShellShortcuts
        shortcuts = PowerShellShortcuts()
    if not args.no_registry:
        from tapesmith.install.registry import UninstallRegistry
        from tapesmith.integration import WinRegBackend
        uninstall_registry = UninstallRegistry()
        registry = WinRegBackend()

    # Das Löschen des Programmordners erst ganz am Ende starten: solange dieser Prozess noch aus dem
    # Ordner läuft, hinterließe `rmdir /s /q` einen halb gelöschten Ordner.
    pending: list[Path] = []
    ok = True
    try:
        lines = uninstall(root=args.root, shortcuts=shortcuts, uninstall_registry=uninstall_registry,
                          registry=registry, quiet=args.quiet, schedule_delete=pending.append)
        text = "\n".join(lines)
    except (ValueError, RuntimeError, OSError) as exc:
        text = _t("Deinstallation fehlgeschlagen: {exc}", exc=exc)
        ok = False

    _log_result(text, ok)
    if sys.stderr is not None:
        print(text, file=sys.stderr if not ok else sys.stdout)
    deleter = schedule_delete or _default_schedule_delete
    for folder in pending:
        deleter(folder)
    return 0 if ok else 1
