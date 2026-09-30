"""Bausteine der Verteilung über Python: Versionsumgebungen (`install.venv`), Ablösung eines
Quellcode-Starts (`install.legacy`), Prozesssuche über Befehlszeilen, Verknüpfungen über
PowerShell, Paketindex der Update-Quellen und ein optionaler echter Durchlauf mit pip.

Nur Fakes und Temp-Ordner: kein echtes pip, keine echte Registry, kein echtes Startmenü, keine
Prozesse dieses PCs. Der echte Durchlauf läuft nur mit `TAPESMITH_SLOW_TESTS=1` und
`TAPESMITH_SLOW_WHEELHOUSE=<Ordner mit allen Wheels>`."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tapesmith import integration as intg
from tapesmith.install import layout, legacy, processes
from tapesmith.install import venv as venv_mod
from tapesmith.install.shortcuts import PowerShellShortcuts
from tapesmith.update.sources import FileSource, GitHubSource, UrlSource
from update_fakes import PYTHON, FakeVenvRun


# ---------- install.venv ----------

def test_base_python_aus_venv_und_pythonw(tmp_path):
    assert venv_mod.base_python("C:/Py/pythonw.exe") == Path("C:/Py/python.exe")
    assert venv_mod.base_python("C:/Py/python.exe") == Path("C:/Py/python.exe")
    assert venv_mod.base_python().name.lower() == "python.exe"


def test_pyvenv_cfg_lesen(tmp_path):
    env = tmp_path / "env"
    env.mkdir()
    assert venv_mod.python_of_env(env) is None and venv_mod.python_version_of_env(env) is None
    (env / "pyvenv.cfg").write_text("home = C:\\Py311\ninclude-system-site-packages = false\n"
                                    "version_info = 3.11.9.final.0\n", encoding="utf-8")
    assert venv_mod.python_of_env(env) == Path("C:\\Py311") / "python.exe"
    assert venv_mod.python_version_of_env(env) == "3.11"


def test_clean_env_isoliert_fremde_umgebungen(monkeypatch):
    monkeypatch.setenv("PYTHONPATH", "C:/fremd")
    monkeypatch.setenv("VIRTUAL_ENV", "C:/fremd/.venv")
    env = venv_mod.clean_env({"X": "1"})
    assert "PYTHONPATH" not in env and "VIRTUAL_ENV" not in env
    assert env["PYTHONNOUSERSITE"] == "1" and env["X"] == "1"


def test_pip_argv_nur_wheels_und_hashes(tmp_path):
    spec = venv_mod.PipSpec(lock_file=tmp_path / "lock.txt", find_links=["D:/wheels"], no_index=True)
    argv = venv_mod.pip_install_argv(tmp_path / "env", spec)
    assert argv[:4] == [str(tmp_path / "env" / "Scripts" / "python.exe"), "-m", "pip", "install"]
    assert "--only-binary=:all:" in argv and "--no-index" in argv
    assert argv[-3:] == ["--require-hashes", "-r", str(tmp_path / "lock.txt")]
    assert argv[argv.index("--find-links") + 1] == "D:/wheels"


def test_provision_komplett_und_ohne_fenster(tmp_path):
    run = FakeVenvRun()
    lines = []
    target = venv_mod.provision(tmp_path, "0.4.0", python=PYTHON,
                                spec=venv_mod.PipSpec(requirements=["tapesmith==0.4.0"]), run=run, log=lines.append)
    assert target == layout.version_dir("0.4.0", tmp_path)
    assert layout.is_complete_version(target)
    assert venv_mod.installed_version(target) == "0.4.0"
    assert run.kinds() == ["venv", "pip", "selftest"]
    for _argv, env, timeout in run.calls:
        assert env is not None and env["PYTHONNOUSERSITE"] == "1" and timeout
    assert len(lines) == 3


@pytest.mark.parametrize("run, step", [
    (FakeVenvRun(venv_rc=1), "venv"),
    (FakeVenvRun(pip_rc=1), "pip"),
    (FakeVenvRun(installed_version="0.3.9"), "version"),
    (FakeVenvRun(selftest_ok=False), "selftest"),
])
def test_provision_fehler_entfernt_den_ordner(tmp_path, run, step):
    with pytest.raises(venv_mod.ProvisionError) as info:
        venv_mod.provision(tmp_path, "0.4.0", python=PYTHON,
                           spec=venv_mod.PipSpec(requirements=["tapesmith==0.4.0"]), run=run)
    assert info.value.step == step
    assert not layout.version_dir("0.4.0", tmp_path).exists()


def test_provision_zeitueberschreitung_und_startfehler(tmp_path):
    spec = venv_mod.PipSpec(requirements=["tapesmith==0.4.0"])
    with pytest.raises(venv_mod.ProvisionError, match="Zeitüberschreitung"):
        venv_mod.provision(tmp_path, "0.4.0", python=PYTHON, spec=spec,
                           run=FakeVenvRun(raises=subprocess.TimeoutExpired("x", 1)))
    with pytest.raises(venv_mod.ProvisionError, match="Start fehlgeschlagen"):
        venv_mod.provision(tmp_path, "0.4.0", python=PYTHON, spec=spec, run=FakeVenvRun(raises=OSError("weg")))
    assert not layout.version_dir("0.4.0", tmp_path).exists()


def test_run_hidden_ohne_konsolenfenster(monkeypatch):
    seen = {}

    def fake_run(argv, **kw):
        seen.update(kw)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(venv_mod.subprocess, "run", fake_run)
    venv_mod.run_hidden(["x"], timeout=5)
    assert seen["creationflags"] == venv_mod.CREATE_NO_WINDOW
    assert seen["stdin"] == subprocess.DEVNULL and seen["timeout"] == 5


# ---------- Quellcode-Start ablösen ----------

def test_source_run_env_erkennt_quellcode_start(tmp_path):
    root = tmp_path / "Programs" / "Tapesmith"
    reg = intg.FakeRegistry()
    assert legacy.source_run_env(reg, root) is None
    reg.set(intg.RUN_KEY, intg.RUN_VALUE, r'"C:\src\tapesmith\.venv\Scripts\pythonw.exe" -m tapesmith.gui.tray')
    assert legacy.source_run_env(reg, root) == Path(r"C:\src\tapesmith\.venv")
    reg.set(intg.RUN_KEY, intg.RUN_VALUE, f'"{root}\\current\\Scripts\\pythonw.exe" -m tapesmith.gui.tray')
    assert legacy.source_run_env(reg, root) is None  # eigene Installation
    reg.set(intg.RUN_KEY, intg.RUN_VALUE, f'"{root}\\current\\Tapesmith.exe" --tray')
    assert legacy.source_run_env(reg, root) is None  # portabler Build: löst die Installation selbst ab
    reg.set(intg.RUN_KEY, intg.RUN_VALUE, r'"C:\anders\python.exe" -m etwas')
    assert legacy.source_run_env(reg, root) is None


def test_stop_source_run_meldet_ergebnis(tmp_path):
    env = tmp_path / ".venv"
    assert "abgelöst" in legacy.stop_source_run(env, stopper=lambda e: True)[0]
    assert "nicht vollständig" in legacy.stop_source_run(env, stopper=lambda e: False)[0]

    def boom(e):
        raise OSError("kaputt")

    assert "kaputt" in legacy.stop_source_run(env, stopper=boom)[0]


def test_tapesmith_prozesse_nur_aus_der_umgebung_und_mit_tapesmith(tmp_path):
    env = tmp_path / ".venv"
    rows = [
        (10, str(env / "Scripts" / "pythonw.exe"), "pythonw.exe -m tapesmith.gui.tray"),
        (11, str(env / "Scripts" / "python.exe"), "python.exe -m pytest"),
        (12, str(tmp_path / "anders" / "pythonw.exe"), "pythonw.exe -m tapesmith.daemon"),
        (13, str(env / "Scripts" / "pythonw.exe"), "pythonw.exe -m tapesmith.daemon"),
        (14, "", "ohne Pfad"),
    ]
    found = processes.tapesmith_processes_in(env, rows=rows, exclude_pids=(13,))
    assert [p.pid for p in found] == [10]


def test_list_command_lines_liest_cim_ausgabe():
    def runner(argv, **kw):
        assert argv[0] == "powershell.exe" and kw["creationflags"] == 0x08000000
        return subprocess.CompletedProcess(argv, 0, "4\tC:\\a.exe\tC:\\a.exe -x\nkaputt\n", "")

    assert processes.list_command_lines(runner=runner) == [(4, "C:\\a.exe", "C:\\a.exe -x")]

    def failing(argv, **kw):
        raise OSError("keine PowerShell")

    assert processes.list_command_lines(runner=failing) == []


@pytest.mark.skipif(sys.platform != "win32", reason="CIM nur unter Windows")
def test_list_command_lines_echt_findet_eigenen_prozess():
    """Echter PowerShell-Aufruf: Spalten per Tabulator getrennt, eigener Prozess mit Pfad dabei."""
    rows = {pid: (exe, cmd) for pid, exe, cmd in processes.list_command_lines()}
    assert os.getpid() in rows
    exe, cmd = rows[os.getpid()]
    assert exe and Path(exe).name.lower().startswith("python")
    assert "pytest" in cmd.lower()


def test_own_pids_enthaelt_eltern_prozess():
    pids = processes.own_pids()
    assert pids[0] == os.getpid() and os.getppid() in pids


# ---------- Verknüpfungen über PowerShell ----------

def test_powershell_shortcuts_uebergibt_werte_als_umgebung(tmp_path):
    calls = []

    def runner(argv, **kw):
        calls.append((argv, kw))
        return subprocess.CompletedProcess(argv, 0, "", "")

    backend = PowerShellShortcuts(runner=runner)
    lnk = tmp_path / "menu" / "Tapesmith.lnk"
    backend.create(lnk, Path("C:/root/current/Scripts/pythonw.exe"), arguments="-m tapesmith.webui.browser",
                   icon=Path("C:/root/app.ico"), workdir=Path("C:/root"), description="Tapesmith")
    argv, kw = calls[0]
    assert argv[0] == "powershell.exe" and "$env:TS_LNK_PATH" in argv[-1]
    assert kw["env"]["TS_LNK_PATH"] == str(lnk)
    assert kw["env"]["TS_LNK_ARGS"] == "-m tapesmith.webui.browser"
    assert kw["env"]["TS_LNK_ICON"] == str(Path("C:/root/app.ico"))
    assert kw["creationflags"] == 0x08000000
    assert lnk.parent.is_dir()


def test_powershell_shortcuts_fehler_wird_oserror(tmp_path):
    backend = PowerShellShortcuts(runner=lambda argv, **kw: subprocess.CompletedProcess(argv, 1, "", "Zugriff verweigert"))
    with pytest.raises(OSError, match="Zugriff verweigert"):
        backend.create(tmp_path / "x.lnk", Path("C:/x/pythonw.exe"))


# ---------- Paketindex der Update-Quellen ----------

def test_pip_options_der_quellen(tmp_path):
    folder = tmp_path / "feed"
    folder.mkdir()
    assert FileSource(folder).pip_options() == {}
    (folder / "tapesmith-0.4.0-py3-none-any.whl").write_bytes(b"w")
    assert FileSource(folder).pip_options() == {"find_links": [str(folder)], "no_index": True}
    (folder / "wheels").mkdir()
    (folder / "wheels" / "pillow-1-cp311-cp311-win_amd64.whl").write_bytes(b"w")
    assert FileSource(folder).pip_options() == {"find_links": [str(folder / "wheels")], "no_index": True}
    assert GitHubSource("example-owner", "tapesmith").pip_options() == {}
    assert UrlSource("https://example.org/feed/").pip_options() == {}


# ---------- Echter Durchlauf (nur auf Wunsch) ----------

@pytest.mark.slow
@pytest.mark.skipif(os.environ.get("TAPESMITH_SLOW_TESTS") != "1" or not os.environ.get("TAPESMITH_SLOW_WHEELHOUSE"),
                    reason="nur mit TAPESMITH_SLOW_TESTS=1 und TAPESMITH_SLOW_WHEELHOUSE")
def test_echte_installation_aus_wheelhouse(tmp_path, monkeypatch):
    """Echtes `python -m venv`, echtes pip (nur aus dem Wheel-Ordner, kein Netz) und echter
    Selbsttest in der neuen Umgebung; keine Registry, kein Startmenü, kein Start."""
    from tapesmith.install import installer

    wheelhouse = Path(os.environ["TAPESMITH_SLOW_WHEELHOUSE"])
    wheel = sorted(wheelhouse.glob("tapesmith-*.whl"))[-1]
    version = wheel.name.split("-")[1]
    # Kurzer Pfad: Qt legt in PySide6 sehr lange Dateinamen ab, der tiefe pytest-Ordner sprengt
    # sonst die 260 Zeichen von Windows (ohne Long Path Support).
    import shutil
    import tempfile

    root = Path(tempfile.mkdtemp(prefix="tsi", dir=os.environ.get("TEMP"))) / "Tapesmith"
    try:
        result = installer.install(version=version, root=root, python=venv_mod.base_python(sys.executable),
                                   spec=venv_mod.PipSpec(requirements=[str(wheel)], find_links=[str(wheelhouse)],
                                                         no_index=True),
                                   start=False)
        assert layout.is_complete_version(layout.version_dir(version, root))
        assert any("Installiert" in line for line in result.lines)
    finally:
        shutil.rmtree(root.parent, ignore_errors=True)
