"""Startbefehle für Oberfläche, Druckdienst und Tray.

Einzige Stelle, die Kommandozeilen für die Prozessarten baut: installierte App und Entwicklung
(`pythonw.exe -m tapesmith.<modul>`); der Zweig für einen eingefrorenen Build (`--daemon|--tray|--app`
der früheren PyInstaller-EXE) bleibt nur für Altinstallationen.
Genutzt von den Registry-Befehlen in `integration.py`, vom Dienststart und von der Tray-App.

Die Arten `gui` und `app` öffnen die Web-Oberfläche im Standardbrowser (`tapesmith.webui.browser`); ein eigenes lokales Fenster gibt es
nicht mehr. Kontextmenü- und URI-Einträge öffnen damit ebenfalls den Browser."""

import os
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from tapesmith import paths
from tapesmith.i18n import _t

KINDS = ("gui", "daemon", "tray", "app")
MODULES = {"gui": "tapesmith.webui.browser", "daemon": "tapesmith.daemon", "tray": "tapesmith.gui.tray",
           "app": "tapesmith.webui.browser"}
FROZEN_FLAGS = {"gui": [], "daemon": ["--daemon"], "tray": ["--tray"], "app": ["--app"]}

DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def gui_python(executable: str | None = None) -> str:
    """`pythonw.exe` neben `executable` (Default `sys.executable`), falls vorhanden, sonst
    dasselbe Executable (Entwicklungsumgebungen ohne `pythonw.exe`, z. B. manche venvs)."""
    exe = executable or sys.executable
    candidate = os.path.join(os.path.dirname(exe), "pythonw.exe")
    return candidate if os.path.isfile(candidate) else exe


def app_argv(kind: str, *extra: str, frozen: bool | None = None, executable: str | None = None) -> list[str]:
    if kind not in KINDS:
        raise ValueError(_t("Unbekannte Art '{kind}', erlaubt: {items}", kind=kind, items=', '.join(KINDS)))
    is_frozen_run = is_frozen() if frozen is None else frozen
    if is_frozen_run:
        exe = executable or sys.executable
        return [exe, *FROZEN_FLAGS[kind], *extra]
    return [gui_python(executable), "-m", MODULES[kind], *extra]


def command_line(argv: Sequence[str]) -> str:
    return subprocess.list2cmdline(list(argv))


def registry_command(kind: str, *extra: str, placeholder: str = "%1", frozen: bool | None = None,
                     executable: str | None = None) -> str:
    """Vollständige Registry-Befehlszeile inkl. Platzhalter (immer in Anführungszeichen), z. B.
    für `<verb>\\command` oder `tapesmith\\shell\\open\\command`."""
    argv = app_argv(kind, *extra, frozen=frozen, executable=executable)
    return command_line(argv) + f' "{placeholder}"'


def spawn_detached(argv: Sequence[str], *, popen: Callable[..., Any] | None = None,
                   env: Mapping[str, str] | None = None, cwd: str | None = None) -> int:
    """Startet `argv` als vom aktuellen Prozess losgelöste Konsolenanwendung (kein eigenes
    Fenster, keine geerbten Handles). Gibt die PID zurück; ein Startfehler wird zu einem
    `RuntimeError` mit Klartext statt eines rohen `OSError`.

    Ohne `cwd` läuft der neue Prozess im App-Datenordner (`paths.app_dir()`, wird bei Bedarf
    angelegt), nicht im Arbeitsordner des Aufrufers: sonst würde z. B. ein USB-Stick als
    Aufrufer-cwd den losgelösten Prozess blockieren, sobald der Stick entfernt wird.

    Das aktuelle `TAPESMITH_HOME` wird immer ausdrücklich weitergereicht (`paths.child_env`)."""
    if popen is None:
        popen = subprocess.Popen
    child_env = paths.child_env(env)
    if cwd is None:
        cwd = str(paths.app_dir())
    try:
        proc = popen(
            list(argv),
            creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            env=child_env,
            cwd=cwd,
        )
    except OSError as exc:
        raise RuntimeError(_t("Start fehlgeschlagen: {exc}", exc=exc)) from exc
    return proc.pid
