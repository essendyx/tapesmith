"""Tests für `p12 gui`: leitet auf `p12 app` um (Hinweis auf stderr, `webui.browser.main`),
`--selftest`/`--selftest-out` rufen den Qt-freien Selbsttest. Kein Browser, kein Qt beim Laden."""

import os
import subprocess
import sys

import pytest

from tapesmith import cli, selftest
from tapesmith.webui import browser


def test_help_listet_gui(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    assert "gui" in capsys.readouterr().out


def test_plugin_laedt_kein_qt():
    code = ("import sys, tapesmith.cli, tapesmith.cli_cmds.base as b; b.discover_commands(); "
            "print('PySide6' in sys.modules)")
    env = dict(os.environ)
    src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                            env=env, timeout=60, check=True)
    assert result.stdout.strip() == "False"


def test_gui_leitet_auf_app_um(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(browser, "main", lambda argv=None: calls.append(argv) or 0)
    assert cli.main(["gui"]) == 0
    assert calls == [[]]
    captured = capsys.readouterr()
    assert "Hinweis: ‚p12 gui‘ heißt jetzt ‚p12 app‘." in captured.err
    assert captured.out == ""


def test_gui_gibt_exit_code_weiter(monkeypatch):
    monkeypatch.setattr(browser, "main", lambda argv=None: 1)
    assert cli.main(["gui"]) == 1


def test_gui_selbsttest_ruft_selftest(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(selftest, "main", lambda argv=None: calls.append(argv) or 0)
    monkeypatch.setattr(browser, "main", lambda argv=None: pytest.fail("kein Browser beim Selbsttest"))
    target = tmp_path / "s.txt"
    assert cli.main(["gui", "--selftest", "--selftest-out", str(target)]) == 0
    assert calls == [["--selftest-out", str(target)]]


def test_gui_selbsttest_ohne_datei(monkeypatch):
    calls = []
    monkeypatch.setattr(selftest, "main", lambda argv=None: calls.append(argv) or 1)
    assert cli.main(["gui", "--selftest"]) == 1
    assert calls == [[]]


def test_gui_selbsttest_echt(tmp_path):
    target = tmp_path / "s.txt"
    assert cli.main(["gui", "--selftest", "--selftest-out", str(target)]) == 0
    assert target.read_text(encoding="utf-8").rstrip().endswith("Selbsttest ok")


def test_gui_route(monkeypatch):
    calls = []
    monkeypatch.setattr(browser, "main", lambda argv=None: calls.append(argv) or 0)
    assert cli.main(["gui", "--route", "/verlauf"]) == 0
    assert calls == [["--route", "/verlauf"]]
