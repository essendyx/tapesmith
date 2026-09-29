"""Ablösung einer alten Installation unter dem früheren App-Namen "P12 Label" (bis 0.2.x).

Nach einer erfolgreichen Tapesmith-Installation entfernt `remove_legacy` die Programmteile der
alten Installation: Programmordner `%LOCALAPPDATA%\\Programs\\P12Label`, Apps-und-Features-Eintrag
`HKCU\\...\\Uninstall\\P12Label`, Autostart-Wert `P12Label`, Startmenü-Ordner "P12 Label" und die
alten Kontextmenü-Einträge. Das URI-Schema `p12label://` bleibt als Alias bestehen (die neue
Installation hat es bereits auf Tapesmith umgestellt), nur die alte Markierung verschwindet.

Benutzerdaten (`%APPDATA%\\P12Label`) werden nie angefasst: die Datenübernahme kopiert sie
(`tapesmith.migrate`), das Original bleibt als Sicherung liegen.

Wie `installer.install()` berührt diese Funktion Registry und Startmenü nur über die übergebenen
Backends; ohne Backend bleibt der jeweilige Teil unberührt. Tests nutzen `FakeRegistry`,
`FakeUninstallRegistry` und Ordner unter `tmp_path`."""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from pathlib import Path

from tapesmith.install import junction, layout, processes
from tapesmith.i18n import _t

LEGACY_DIR_NAME = "P12Label"
LEGACY_EXE = "P12Label.exe"
LEGACY_UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\P12Label"
LEGACY_RUN_VALUE = "P12Label"
LEGACY_MARKER = "P12LabelManaged"
LEGACY_START_MENU_NAME = "P12 Label"
LEGACY_SHORTCUTS = ("P12 Label.lnk", "P12 Label deinstallieren.lnk")
LEGACY_VERB_PREFIX = "P12Label."
LEGACY_URI_SCHEME = "p12label"

GUARD_MESSAGE = (
    "TAPESMITH_LEGACY_INSTALL_ROOT fehlt: unter pytest ist die echte alte Installation gesperrt. Tests brauchen TAPESMITH_LEGACY_INSTALL_ROOT=<eigener Temp-Ordner>.")


def default_root() -> Path:
    """`%LOCALAPPDATA%\\Programs\\P12Label` (überschreibbar per `TAPESMITH_LEGACY_INSTALL_ROOT`).
    Unter pytest ohne Override: `RuntimeError`."""
    override = os.environ.get("TAPESMITH_LEGACY_INSTALL_ROOT")
    if override:
        return Path(override)
    if "PYTEST_CURRENT_TEST" in os.environ:
        raise RuntimeError(GUARD_MESSAGE)
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Programs" / LEGACY_DIR_NAME


def looks_like_install(root: Path) -> bool:
    """Liegt unter `root` eine alte Installation (install.json oder versions)?"""
    return (root / "install.json").is_file() or (root / "versions").is_dir()


def _real(path: Path | str) -> str:
    return os.path.normcase(os.path.realpath(os.path.abspath(str(path)))).rstrip("\\/")


def _check_legacy_root(root: Path, new_root: Path | None) -> None:
    """Sicherheitsnetz vor dem Löschen: Ordnername `P12Label`, eine Installation darin, nicht die
    neue Installation, keine Überschneidung mit Benutzerdaten (alt oder neu)."""
    if root.name.lower() != LEGACY_DIR_NAME.lower():
        raise ValueError(_t("Alte Installation nicht entfernt: unerwarteter Ordnername {root}", root=root))
    if not looks_like_install(root):
        raise ValueError(_t("Alte Installation nicht entfernt: in {root} fehlt install.json", root=root))
    real = _real(root)
    if new_root is not None and _real(new_root) == real:
        raise ValueError(_t("Alte Installation nicht entfernt: Ordner ist die neue Installation"))
    data_dirs = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        data_dirs += [Path(appdata) / LEGACY_DIR_NAME, Path(appdata) / "Tapesmith"]
    for env in ("TAPESMITH_HOME", "P12LABEL_HOME"):
        if os.environ.get(env):
            data_dirs.append(Path(os.environ[env]))
    for data in data_dirs:
        d = _real(data)
        if d == real or d.startswith(real + os.sep) or real.startswith(d + os.sep):
            raise ValueError(_t("Alte Installation nicht entfernt: {root} überschneidet sich mit Benutzerdaten", root=root))


def _default_stop(root: Path) -> bool:
    running = processes.processes_under(root, exclude_pids=(os.getpid(),))
    if not running:
        return True
    return not processes.terminate([p.pid for p in running])


def _delete_folder(root: Path, schedule_delete: Callable[[Path], None] | None) -> str:
    link = layout.current_link(root)
    if junction.read_junction(link) is not None:
        os.rmdir(link)  # nur die Junction, nie ihr Ziel über die Verknüpfung
    try:
        shutil.rmtree(root)
        return _t("Alter Programmordner entfernt: {root}", root=root)
    except OSError:
        if schedule_delete is None:
            from tapesmith.install.uninstaller import _default_schedule_delete
            schedule_delete = _default_schedule_delete
        schedule_delete(root)
        return _t("Alter Programmordner wird entfernt: {root}", root=root)


def remove_legacy(*, root: Path | None, new_root: Path | None = None, shortcuts=None,
                  menu_dir: Path | None = None, uninstall_registry=None, registry=None,
                  stopper: Callable[[Path], bool] | None = None,
                  schedule_delete: Callable[[Path], None] | None = None) -> list[str]:
    """Entfernt die Programmteile einer alten "P12 Label"-Installation. Gibt Protokollzeilen
    zurück; Fehler einzelner Teile brechen nicht ab, sondern landen als Zeile im Protokoll."""
    lines: list[str] = []

    if root is not None and root.exists() and looks_like_install(root):
        try:
            _check_legacy_root(root, new_root)
            stop = stopper or _default_stop
            if not stop(root):
                lines.append(_t("Alte Installation: Prozesse ließen sich nicht beenden, Ordner bleibt"))
            else:
                lines.append(_delete_folder(root, schedule_delete))
        except (ValueError, OSError) as exc:
            lines.append(str(exc))

    if shortcuts is not None and menu_dir is not None:
        removed = False
        for name in LEGACY_SHORTCUTS:
            path = menu_dir / name
            if shortcuts.exists(path):
                shortcuts.delete(path)
                removed = True
        try:
            menu_dir.rmdir()  # nur, wenn leer
        except OSError:
            pass
        if removed:
            lines.append(_t("Alter Startmenü-Eintrag entfernt: {menu_dir}", menu_dir=menu_dir))

    if uninstall_registry is not None and uninstall_registry.get("DisplayName") is not None:
        uninstall_registry.delete_tree()
        lines.append(_t("Alter Eintrag unter Installierte Apps entfernt"))

    if registry is not None:
        from tapesmith import integration

        current = registry.get(integration.RUN_KEY, LEGACY_RUN_VALUE)
        if current is not None:
            registry.delete_value(integration.RUN_KEY, LEGACY_RUN_VALUE)
            lines.append(_t("Alter Autostart-Eintrag entfernt"))
        removed_verbs = 0
        for verb in integration.CONTEXT_VERBS:
            old_key = LEGACY_VERB_PREFIX + verb.key.split(".", 1)[1]
            for target in verb.targets:
                path = f"{integration.HKCU_CLASSES}\\{target}\\shell\\{old_key}"
                if registry.get(path, LEGACY_MARKER) == "1":
                    registry.delete_tree(path)
                    removed_verbs += 1
        if removed_verbs:
            lines.append(_t("Alte Kontextmenü-Einträge entfernt: {removed_verbs}", removed_verbs=removed_verbs))
        uri_path = f"{integration.HKCU_CLASSES}\\{LEGACY_URI_SCHEME}"
        if registry.get(uri_path, LEGACY_MARKER) == "1":
            if registry.get(uri_path, integration.MARKER) == "1":
                # Alias ist schon auf Tapesmith umgestellt: nur die alte Markierung entfernen.
                registry.delete_value(uri_path, LEGACY_MARKER)
                lines.append(_t("URI-Schema p12label:// zeigt jetzt auf Tapesmith"))
            else:
                registry.delete_tree(uri_path)
                lines.append(_t("Altes URI-Schema p12label:// entfernt"))

    return lines
