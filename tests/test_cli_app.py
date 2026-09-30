"""Tests für `tapesmith app`: ruft `webui.browser.main` mit passenden Argumenten und öffnet die
Oberfläche im Standardbrowser (hier gemockt, nie ein echter Browser)."""

import inspect
import os
import subprocess
import sys

from tapesmith import cli
from tapesmith.cli_cmds import app as app_cmd
from tapesmith.webui import browser


def test_app_route_ruft_browser_main(monkeypatch):
    seen = []
    monkeypatch.setattr(browser, "main", lambda argv: seen.append(argv) or 0)
    assert cli.main(["app", "--route", "/verlauf"]) == 0
    assert seen == [["--route", "/verlauf"]]


def test_app_uri(monkeypatch):
    seen = []
    monkeypatch.setattr(browser, "main", lambda argv: seen.append(argv) or 0)
    assert cli.main(["app", "--uri", "tapesmith://print?template=x"]) == 0
    assert seen == [["--uri", "tapesmith://print?template=x"]]


def test_app_open_und_path_browser_flagge_ist_wirkungslos(monkeypatch):
    seen = []
    monkeypatch.setattr(browser, "main", lambda argv: seen.append(argv) or 0)
    assert cli.main(["app", "--open", "lines", "--path", "C:\\x\\a.txt", "--browser"]) == 0
    assert seen == [["--open", "lines", "--path", "C:\\x\\a.txt"]]


def test_app_oeffnet_browser_mit_token_url(monkeypatch):
    urls = []
    monkeypatch.setattr(browser.config, "load_config", lambda: {})
    monkeypatch.setattr(browser, "connect_session", lambda cfg: {"port": 8712, "token": "tok"})
    monkeypatch.setattr(browser, "default_opener", lambda url: urls.append(url))
    assert cli.main(["app", "--route", "/verlauf"]) == 0
    assert urls == ["http://127.0.0.1:8712/verlauf#t=tok"]


def test_app_ohne_dienst_exit_1_mit_meldung(monkeypatch, capsys):
    def failing(route):
        raise RuntimeError("Druckdienst startet nicht")

    monkeypatch.setattr(browser, "open_app", failing)
    assert cli.main(["app"]) == 1
    assert "Druckdienst startet nicht" in capsys.readouterr().err


def test_cli_import_laedt_weder_webview_noch_browsermodul():
    code = ("import sys, tapesmith.cli, tapesmith.cli_cmds.base as b; b.discover_commands(); "
            "print('webview' in sys.modules, 'tapesmith.webui.browser' in sys.modules)")
    env = dict(os.environ)
    src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                            env=env, timeout=60, check=True)
    assert result.stdout.strip() == "False False"


def test_app_cmd_quelltext_keine_gedankenstriche():
    quelltext = inspect.getsource(app_cmd)
    assert "\u2013" not in quelltext
    assert "\u2014" not in quelltext
