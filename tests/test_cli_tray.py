"""Tests für `tapesmith tray`: startet die Tray-App losgelöst oder im Vordergrund. Nie echte
Prozesse: `SPAWN` und `gui.tray.main` werden ersetzt."""

import os
import subprocess
import sys

from tapesmith import cli, launch
from tapesmith.cli_cmds import tray as tray_cmd


def test_tray_startet_losgeloest(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(tray_cmd, "SPAWN", lambda argv: calls.append(list(argv)) or 4711)
    assert cli.main(["tray"]) == 0
    assert calls == [launch.app_argv("tray")]
    assert "Tray-App gestartet" in capsys.readouterr().out


def test_tray_no_hotkeys_wird_durchgereicht(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(tray_cmd, "SPAWN", lambda argv: calls.append(list(argv)) or 1)
    assert cli.main(["tray", "--no-hotkeys"]) == 0
    assert calls == [launch.app_argv("tray", "--no-hotkeys")]


def test_tray_startfehler(monkeypatch, capsys):
    def fail(argv):
        raise RuntimeError("Start fehlgeschlagen: kaputt")

    monkeypatch.setattr(tray_cmd, "SPAWN", fail)
    assert cli.main(["tray"]) == 1
    assert "kaputt" in capsys.readouterr().err


def test_tray_vordergrund(monkeypatch):
    import tapesmith.gui.tray as gui_tray

    seen = []
    monkeypatch.setattr(tray_cmd, "SPAWN", lambda argv: (_ for _ in ()).throw(AssertionError("kein Spawn")))
    monkeypatch.setattr(gui_tray, "main", lambda argv: seen.append(argv) or 0)
    assert cli.main(["tray", "--foreground", "--no-hotkeys"]) == 0
    assert seen == [["--no-hotkeys"]]


def test_tray_plugin_laedt_kein_qt():
    code = ("import sys, tapesmith.cli, tapesmith.cli_cmds.base as b; b.discover_commands(); "
            "print('PySide6' in sys.modules)")
    env = dict(os.environ)
    src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                            env=env, timeout=60, check=True)
    assert result.stdout.strip() == "False"
