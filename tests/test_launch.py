"""Tests für `launch.py`, die einzige Stelle, die Kommandozeilen für gui/daemon/tray baut."""

import subprocess

import pytest

from tapesmith import launch


def test_app_argv_frozen_daemon():
    argv = launch.app_argv("daemon", frozen=True, executable=r"C:\P\Tapesmith.exe")
    assert argv == [r"C:\P\Tapesmith.exe", "--daemon"]


def test_app_argv_frozen_tray():
    argv = launch.app_argv("tray", frozen=True, executable=r"C:\P\Tapesmith.exe")
    assert argv == [r"C:\P\Tapesmith.exe", "--tray"]


def test_app_argv_frozen_gui_keine_zusatzflagge():
    argv = launch.app_argv("gui", frozen=True, executable=r"C:\P\Tapesmith.exe")
    assert argv == [r"C:\P\Tapesmith.exe"]


def test_app_argv_dev_mit_pythonw(tmp_path):
    py = tmp_path / "python.exe"
    py.write_bytes(b"")
    pyw = tmp_path / "pythonw.exe"
    pyw.write_bytes(b"")
    argv = launch.app_argv("tray", frozen=False, executable=str(py))
    assert argv == [str(pyw), "-m", "tapesmith.gui.tray"]


def test_app_argv_dev_ohne_pythonw(tmp_path):
    py = tmp_path / "python.exe"
    py.write_bytes(b"")
    argv = launch.app_argv("daemon", frozen=False, executable=str(py))
    assert argv == [str(py), "-m", "tapesmith.daemon"]


def test_app_argv_gui_modul(tmp_path):
    py = tmp_path / "python.exe"
    py.write_bytes(b"")
    argv = launch.app_argv("gui", frozen=False, executable=str(py))
    assert argv == [str(py), "-m", "tapesmith.webui.browser"]


def test_app_argv_unbekannte_art():
    with pytest.raises(ValueError):
        launch.app_argv("x")


def test_command_line_quotet_leerzeichen():
    assert launch.command_line(["C:\\Program Files\\a.exe", "--x"]) == '"C:\\Program Files\\a.exe" --x'


def test_registry_command_frozen():
    cmd = launch.registry_command("gui", "--open", "batch", "--path", frozen=True,
                                  executable=r"C:\Program Files\P12\Tapesmith.exe")
    assert cmd == '"C:\\Program Files\\P12\\Tapesmith.exe" --open batch --path "%1"'


def test_registry_command_platzhalter_anpassbar():
    cmd = launch.registry_command("gui", "--uri", frozen=True, executable=r"C:\P\Tapesmith.exe",
                                  placeholder="%L")
    assert cmd.endswith('"%L"')


def test_spawn_detached_flags_und_pid():
    captured = {}

    def fake_popen(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs

        class P:
            pid = 4242

        return P()

    pid = launch.spawn_detached(["prog.exe", "--tray"], popen=fake_popen)
    assert pid == 4242
    assert captured["argv"] == ["prog.exe", "--tray"]
    flags = captured["kwargs"]["creationflags"]
    assert flags & launch.DETACHED_PROCESS
    assert flags & launch.CREATE_NEW_PROCESS_GROUP
    assert flags & launch.CREATE_NO_WINDOW
    assert captured["kwargs"]["stdin"] == subprocess.DEVNULL
    assert captured["kwargs"]["stdout"] == subprocess.DEVNULL
    assert captured["kwargs"]["stderr"] == subprocess.DEVNULL
    assert captured["kwargs"]["close_fds"] is True


def test_spawn_detached_env_default_enthaelt_tapesmith_home(monkeypatch, tmp_path):
    # eigener Unterordner statt eines festen Pfads: spawn_detached legt ohne `cwd` jetzt
    # paths.app_dir() an, das darf nicht außerhalb der Testisolation landen.
    home = tmp_path / "p12-test"
    monkeypatch.setenv("TAPESMITH_HOME", str(home))
    captured = {}

    def fake_popen(argv, **kwargs):
        captured["env"] = kwargs["env"]

        class P:
            pid = 1

        return P()

    launch.spawn_detached(["prog.exe"], popen=fake_popen)
    assert captured["env"].get("TAPESMITH_HOME") == str(home)


def test_spawn_detached_oserror_wird_zu_runtimeerror():
    def fake_popen(argv, **kwargs):
        raise OSError("nope")

    with pytest.raises(RuntimeError, match="Start fehlgeschlagen"):
        launch.spawn_detached(["prog.exe"], popen=fake_popen)


def test_is_frozen_default_false():
    assert launch.is_frozen() is False


def test_gui_python_mit_pythonw(tmp_path):
    py = tmp_path / "python.exe"
    py.write_bytes(b"")
    pyw = tmp_path / "pythonw.exe"
    pyw.write_bytes(b"")
    assert launch.gui_python(str(py)) == str(pyw)


def test_gui_python_ohne_pythonw(tmp_path):
    py = tmp_path / "python.exe"
    py.write_bytes(b"")
    assert launch.gui_python(str(py)) == str(py)


def test_spawn_detached_reicht_tapesmith_home_auch_bei_eigenem_env_weiter(monkeypatch, tmp_path):
    # Jeder Kindprozess erbt TAPESMITH_HOME ausdrücklich, auch wenn der Aufrufer ein eigenes env baut
    home = tmp_path / "p12-test"
    monkeypatch.setenv("TAPESMITH_HOME", str(home))
    captured = {}

    def fake_popen(argv, **kwargs):
        captured["env"] = kwargs["env"]

        class P:
            pid = 1

        return P()

    launch.spawn_detached(["prog.exe"], popen=fake_popen, env={"PATH": "x"})
    assert captured["env"]["TAPESMITH_HOME"] == str(home)
    assert captured["env"]["PATH"] == "x"


def test_spawn_detached_ohne_home_unter_pytest_startet_nichts(monkeypatch, tmp_path):
    monkeypatch.delenv("TAPESMITH_HOME", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    started = []
    with pytest.raises(RuntimeError, match="TAPESMITH_HOME"):
        launch.spawn_detached(["prog.exe"], popen=lambda *a, **k: started.append(a), cwd=str(tmp_path))
    assert started == []
