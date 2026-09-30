"""Tests für `tapesmith.install.uninstaller` (Deinstallation ohne Adminrechte).

Ausschließlich Fakes/Temp-Ordner: nie die echte Registry, das echte Startmenü, echtes
`%LOCALAPPDATA%` oder laufende Prozesse. Benutzerdaten (`%APPDATA%\\Tapesmith`, hier über
`TAPESMITH_HOME` auf Temp) bleiben unberührt."""

from __future__ import annotations

import subprocess
from pathlib import Path

from tapesmith import integration as intg
from tapesmith import launch
from tapesmith.install import installer, junction, layout, processes, uninstaller
from tapesmith.install.registry import FakeUninstallRegistry
from tapesmith.install.shortcuts import FakeShortcuts
from update_fakes import PYTHON, FakeVenvRun


def _install(**kw):
    kw.setdefault("python", PYTHON)
    kw.setdefault("run", FakeVenvRun())
    return installer.install(**kw)


def _start_menu(tmp_path, monkeypatch):
    menu = tmp_path / "start_menu"
    monkeypatch.setenv("TAPESMITH_START_MENU_DIR", str(menu))
    return menu


# ---------- 8. vollständige Deinstallation ----------

def test_uninstall_entfernt_alles_ausser_benutzerdaten(tmp_path, monkeypatch):
    menu = _start_menu(tmp_path, monkeypatch)
    app_data = tmp_path / "appdata-tapesmith"
    monkeypatch.setenv("TAPESMITH_HOME", str(app_data))
    app_data.mkdir()
    (app_data / "calibration.json").write_text("{}", encoding="utf-8")

    root = tmp_path / "root"
    shortcuts = FakeShortcuts()
    uninstall_registry = FakeUninstallRegistry()
    registry = intg.FakeRegistry()
    _install(version="0.2.0", root=root, shortcuts=shortcuts,
                      uninstall_registry=uninstall_registry, registry=registry, start=False)

    app_lnk = menu / "Tapesmith.lnk"
    uninstall_lnk = menu / "Tapesmith deinstallieren.lnk"
    assert shortcuts.exists(app_lnk) and shortcuts.exists(uninstall_lnk)
    assert uninstall_registry.get("DisplayName") == "Tapesmith"
    assert registry.get(intg.RUN_KEY, intg.RUN_VALUE) is not None

    scheduled = []
    lines = uninstaller.uninstall(root=root, shortcuts=shortcuts, uninstall_registry=uninstall_registry,
                                  registry=registry, schedule_delete=lambda r: scheduled.append(r))

    assert not shortcuts.exists(app_lnk)
    assert not shortcuts.exists(uninstall_lnk)
    assert uninstall_registry.get("DisplayName") is None
    assert registry.get(intg.RUN_KEY, intg.RUN_VALUE) is None
    assert junction.read_junction(layout.current_link(root)) is None
    assert not layout.current_link(root).exists()

    assert scheduled == [root]
    assert any("%APPDATA%\\Tapesmith" in line for line in lines)

    # Benutzerdaten unangetastet (TAPESMITH_HOME auf Temp, nie root).
    assert (app_data / "calibration.json").exists()


def test_uninstall_ohne_backends_beruehrt_nichts(tmp_path):
    root = tmp_path / "root"
    _install(version="0.2.0", root=root, start=False)
    scheduled = []

    lines = uninstaller.uninstall(root=root, shortcuts=None, uninstall_registry=None, registry=None,
                                  schedule_delete=lambda r: scheduled.append(r))

    assert scheduled == [root]
    assert junction.read_junction(layout.current_link(root)) is None
    assert not any("Registry" in line or "Startmenü" in line for line in lines)


def test_uninstall_stoppt_laufende_prozesse(tmp_path, monkeypatch):
    root = tmp_path / "root"
    _install(version="0.2.0", root=root, start=False)

    fake_proc = processes.ProcessInfo(pid=99999, exe=str(root / "current" / "Scripts" / "pythonw.exe"))
    monkeypatch.setattr(uninstaller.processes, "processes_under", lambda r, **kw: [fake_proc])
    calls = []

    uninstaller.uninstall(root=root, stopper=lambda r: calls.append(r) or True,
                          schedule_delete=lambda r: None)

    assert calls == [root]


def test_uninstall_ohne_junction_kein_fehler(tmp_path):
    root = tmp_path / "root"
    (root / "versions").mkdir(parents=True)  # Installation ohne Junction (ohne Kennzeichen verweigert)
    scheduled = []

    lines = uninstaller.uninstall(root=root, schedule_delete=lambda r: scheduled.append(r))

    assert scheduled == [root]
    assert any("%APPDATA%\\Tapesmith" in line for line in lines)


def test_default_schedule_delete_ruft_spawn_mit_ping_und_rmdir(tmp_path):
    calls = []
    uninstaller._default_schedule_delete(tmp_path / "root", spawn=lambda command: calls.append(command))

    assert calls == [uninstaller.delete_command(tmp_path / "root")]
    command = calls[0]
    assert command.startswith("cmd.exe /d /s /c ")
    assert "ping -n 4 127.0.0.1" in command and f'rmdir /s /q "{tmp_path / "root"}"' in command


def test_delete_command_ohne_backslash_escapes():
    """Python quotiert eine argv-Liste für cmd.exe mit Backslash-Escapes vor den inneren
    Anführungszeichen, die cmd nicht versteht; der Programmordner blieb nach der Deinstallation
    stehen. Darum eine fertige Befehlszeile mit /s (äußere Anführungszeichen) statt einer Liste."""
    root = Path(r"C:\Users\Max Muster\AppData\Local\Programs\Tapesmith")
    command = uninstaller.delete_command(root)
    assert '\\"' not in command
    assert command == f'cmd.exe /d /s /c "ping -n 4 127.0.0.1 >nul & rmdir /s /q "{root}""'


def test_delete_command_loescht_ordner_mit_leerzeichen_wirklich(tmp_path):
    root = tmp_path / "Programme mit Leerzeichen" / "Tapesmith"
    (root / "versions" / "0.2.0").mkdir(parents=True)
    (root / "versions" / "0.2.0" / "Tapesmith.exe").write_bytes(b"exe")
    result = subprocess.run(uninstaller.delete_command(root, wait_s=0), capture_output=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert not root.exists()
    assert root.parent.is_dir()


def test_default_schedule_delete_startet_losgeloest_mit_fertiger_befehlszeile(tmp_path, monkeypatch):
    seen = {}

    def fake_popen(args, **kwargs):
        seen["args"] = args
        seen["kwargs"] = kwargs

        class Proc:
            pid = 4711
        return Proc()

    monkeypatch.setattr(uninstaller.subprocess, "Popen", fake_popen)
    uninstaller._default_schedule_delete(tmp_path / "root")
    assert seen["args"] == uninstaller.delete_command(tmp_path / "root")
    assert seen["kwargs"]["creationflags"] & launch.DETACHED_PROCESS


# ---------- uninstaller.main() (EXE-Weiche) ----------

def _uninstall_log():
    from tapesmith import paths

    path = paths.log_dir() / "uninstall.log"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def test_uninstaller_main_erfolg_ohne_backends_nur_log(tmp_path):
    root = tmp_path / "root"
    _install(version="0.2.0", root=root, start=False)
    scheduled = []

    code = uninstaller.main(["--root", str(root), "--no-shortcuts", "--no-registry"],
                            schedule_delete=lambda r: scheduled.append(r))

    assert code == 0
    assert scheduled == [root]
    log = _uninstall_log()
    assert " OK " in log and "%APPDATA%\\Tapesmith" in log


def test_uninstaller_hat_kein_meldungsfenster():
    assert not hasattr(uninstaller, "show_message")
    assert not hasattr(uninstaller, "UNINSTALL_TITLE")


def test_uninstaller_main_quiet(tmp_path):
    root = tmp_path / "root"
    _install(version="0.2.0", root=root, start=False)

    code = uninstaller.main(["--root", str(root), "--no-shortcuts", "--no-registry", "--quiet"],
                            schedule_delete=lambda r: None)

    assert code == 0
