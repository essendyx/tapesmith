"""Tests für `webui.browser`: Routen, Verbindung, Öffnen im Standardbrowser.

Nie ein echter Browser, nie ein echter Dienst, nie ein echter Port."""

from __future__ import annotations

import inspect
import json
import os
import subprocess
import sys
import urllib.parse
import webbrowser
from types import SimpleNamespace
from urllib.parse import unquote

import pytest

from tapesmith.webui import browser
from tapesmith.webui.browser import app_url, build_route, check_health, connect_session, open_app, safe_route


# ---------- build_route / app_url ----------

def test_build_route_standard():
    assert build_route() == "/schnelldruck"


def test_build_route_eigene_route():
    assert build_route(route="/verlauf") == "/verlauf"


def test_build_route_uri():
    uri = "tapesmith://print?template=datentraeger&sn=1"
    route = build_route(uri=uri)
    assert route.startswith("/aktion?uri=")
    assert unquote(route.split("uri=", 1)[1]) == uri


def test_build_route_open_path():
    route = build_route(open_action="lines", path="C:\\x\\a.txt")
    assert route.startswith("/aktion?")
    assert "open=lines" in route
    assert "path=" in route
    assert unquote(route.split("path=", 1)[1]) == "C:\\x\\a.txt"


def test_build_route_uri_gewinnt_vor_open():
    assert build_route(uri="tapesmith://print", open_action="lines", path="C:/a").startswith("/aktion?uri=")


def test_app_url():
    assert app_url(8712, "tok", "/verlauf") == "http://127.0.0.1:8712/verlauf#t=tok"


# ---------- safe_route ----------

@pytest.mark.parametrize("good", ["/", "/verlauf", "/einstellungen?abschnitt=updates",
                                  "/aktion?uri=tapesmith%3A%2F%2Fx"])
def test_safe_route_gueltig(good):
    assert safe_route(good) == good


@pytest.mark.parametrize("bad", ["", "verlauf", "//evil.example/x", "/\\evil.example", "http://x/", "/a#t=x",
                                 "/a\nb", "/" + "x" * 3000, 42, None])
def test_safe_route_ungueltig(bad):
    assert safe_route(bad) is None


# ---------- check_health ----------

class _FakeResponse:
    def __init__(self, body: dict):
        self._body = json.dumps(body).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_check_health_ok():
    def opener(url, timeout=None):
        assert "127.0.0.1" in url
        return _FakeResponse({"ok": True, "home_key": "abc"})

    assert check_health(8712, opener=opener) == {"ok": True, "home_key": "abc"}


def test_check_health_fehler():
    def opener(url, timeout=None):
        raise OSError("nicht erreichbar")

    assert check_health(8712, opener=opener) is None


# ---------- connect_session ----------

class _FakeClient:
    def __init__(self, calls: list):
        self._calls = calls

    def close(self):
        self._calls.append("closed")


def test_connect_session_erfolg():
    calls = []

    def ensure(cfg, *, client, spawn=None):
        calls.append(("ensure", client))
        return _FakeClient(calls)

    sessions = iter([None, {"port": 8712, "token": "tok", "home_key": "abc"}])

    def read():
        return next(sessions, {"port": 8712, "token": "tok", "home_key": "abc"})

    def health(port, timeout_s=1.0):
        assert port == 8712
        return {"home_key": "abc"}

    clock_values = iter([0.0, 0.0, 1.0])
    slept = []

    session = connect_session({"daemon": {"enabled": True}}, ensure=ensure, read=read, health=health,
                              expected_home="abc", timeout_s=5.0, sleep=slept.append,
                              clock=lambda: next(clock_values, 99.0))

    assert session == {"port": 8712, "token": "tok", "home_key": "abc"}
    assert calls[0] == ("ensure", "gui")
    assert "closed" in calls
    assert slept == [0.2]


def test_connect_session_falscher_home_key_zeitablauf():
    def ensure(cfg, *, client, spawn=None):
        return _FakeClient([])

    def read():
        return {"port": 8712, "token": "tok", "home_key": "anderer"}

    def health(port, timeout_s=1.0):
        return {"home_key": "anderer"}

    clock_values = iter([0.0, 1.0, 2.0, 6.0])

    with pytest.raises(RuntimeError, match="antwortet nicht"):
        connect_session({"daemon": {"enabled": True}}, ensure=ensure, read=read, health=health,
                        expected_home="abc", timeout_s=5.0, sleep=lambda s: None,
                        clock=lambda: next(clock_values, 99.0))


def test_connect_session_daemon_deaktiviert_kein_ensure():
    def ensure(cfg, *, client, spawn=None):
        raise AssertionError("ensure haette nicht aufgerufen werden duerfen")

    with pytest.raises(RuntimeError, match="daemon.enabled"):
        connect_session({"daemon": {"enabled": False}}, ensure=ensure, read=lambda: None)


def test_connect_session_ignoriert_altes_web_enabled_false():
    """`web.enabled` gibt es nicht mehr: ein alter Eintrag `false` schaltet nichts ab."""
    calls = []

    def ensure(cfg, *, client, spawn=None):
        calls.append(("ensure", client))
        return _FakeClient(calls)

    session = connect_session({"daemon": {"enabled": True}, "web": {"enabled": False}}, ensure=ensure,
                              read=lambda: {"port": 8712, "token": "tok", "home_key": "abc"},
                              health=lambda port, timeout_s=1.0: {"home_key": "abc"},
                              expected_home="abc", timeout_s=5.0, sleep=lambda s: None,
                              clock=lambda: 0.0)

    assert session["token"] == "tok"
    assert calls[0] == ("ensure", "gui")


class _Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def test_connect_session_laufender_dienst_ohne_sitzung_meldet_sofort():
    clock = _Clock()

    def ensure(cfg, *, client, spawn=None):
        return _FakeClient([])  # Dienst lief schon, nichts gestartet

    with pytest.raises(RuntimeError, match="ohne Web-Oberfläche"):
        connect_session({"daemon": {"enabled": True}}, ensure=ensure, read=lambda: None,
                        health=lambda port, timeout_s=1.0: None, expected_home="abc",
                        timeout_s=60.0, sleep=clock.sleep, clock=clock,
                        spawn=lambda argv: pytest.fail("kein Start erwartet"))
    assert clock.now <= 3.0


def test_connect_session_frisch_gestarteter_dienst_wartet_bis_zur_sitzung():
    clock = _Clock()
    spawned = []

    def ensure(cfg, *, client, spawn=None):
        spawn(["p12d"])
        return _FakeClient([])

    def read():
        return {"port": 8712, "token": "t", "home_key": "abc"} if clock.now >= 6.0 else None

    session = connect_session({"daemon": {"enabled": True}}, ensure=ensure, read=read,
                              health=lambda port, timeout_s=1.0: {"home_key": "abc"}, expected_home="abc",
                              timeout_s=20.0, sleep=clock.sleep, clock=clock,
                              spawn=lambda argv: spawned.append(list(argv)) or 1)
    assert session["port"] == 8712
    assert spawned == [["p12d"]]


# ---------- open_app ----------

def test_open_app_oeffnet_browser_mit_token_url():
    opened = []
    configs = []

    def connector(cfg):
        configs.append(cfg)
        return {"port": 8712, "token": "tok"}

    url = open_app("/einstellungen?abschnitt=updates", config_loader=lambda: {"x": 1},
                   connector=connector, opener=opened.append)
    assert url == "http://127.0.0.1:8712/einstellungen?abschnitt=updates#t=tok"
    assert opened == [url]
    assert configs == [{"x": 1}]


def test_open_app_standardroute_ist_schnelldruck():
    opened = []
    open_app(config_loader=dict, connector=lambda cfg: {"port": 1, "token": "t"}, opener=opened.append)
    assert opened == ["http://127.0.0.1:1/schnelldruck#t=t"]


def test_open_app_ungueltige_route_oeffnet_nichts():
    opened = []
    with pytest.raises(ValueError, match="Ungültige Startseite"):
        open_app("//evil.example", config_loader=dict,
                 connector=lambda cfg: pytest.fail("kein Dienststart"), opener=opened.append)
    assert opened == []


def test_open_app_dienstfehler_wird_weitergereicht():
    opened = []

    def connector(cfg):
        raise RuntimeError("Druckdienst startet nicht")

    with pytest.raises(RuntimeError, match="Druckdienst startet nicht"):
        open_app("/", config_loader=dict, connector=connector, opener=opened.append)
    assert opened == []


def test_open_app_standardwerte_werden_spaet_nachgeschlagen(monkeypatch):
    opened = []
    monkeypatch.setattr(browser.config, "load_config", lambda: {"geladen": True})
    monkeypatch.setattr(browser, "connect_session", lambda cfg: {"port": 9, "token": "z"} if cfg else None)
    monkeypatch.setattr(browser, "default_opener", opened.append)
    assert open_app("/verlauf") == "http://127.0.0.1:9/verlauf#t=z"
    assert opened == ["http://127.0.0.1:9/verlauf#t=z"]


# ---------- default_opener (webbrowser gemockt) ----------

def test_default_opener_nutzt_webbrowser(monkeypatch):
    calls = []
    monkeypatch.setattr(browser.webbrowser, "open", lambda url: calls.append(url) or True)
    browser.default_opener("http://127.0.0.1:1/#t=x")
    assert calls == ["http://127.0.0.1:1/#t=x"]


def test_default_opener_ohne_browser_wirft(monkeypatch):
    monkeypatch.setattr(browser.webbrowser, "open", lambda url: False)
    with pytest.raises(RuntimeError, match="Standardbrowser"):
        browser.default_opener("http://127.0.0.1:1/")


def test_default_opener_webbrowser_fehler_wird_runtimeerror(monkeypatch):
    def fail(url):
        raise webbrowser.Error("kaputt")

    monkeypatch.setattr(browser.webbrowser, "open", fail)
    with pytest.raises(RuntimeError, match="kaputt"):
        browser.default_opener("http://127.0.0.1:1/")


# ---------- main ----------

@pytest.mark.parametrize("argv, route", [
    ([], "/schnelldruck"),
    (["--route", "/verlauf"], "/verlauf"),
    (["--uri", "tapesmith://text?l=x"], "/aktion?uri=tapesmith%3A%2F%2Ftext%3Fl%3Dx"),
    (["--open", "lines", "--path", "C:/a.txt"], "/aktion?open=lines&path=C%3A%2Fa.txt"),
    (["--browser", "--route", "/galerie"], "/galerie"),
])
def test_main_oeffnet_route(argv, route):
    routes = []
    assert browser.main(argv, opener=routes.append) == 0
    assert routes == [route]


def test_main_nimmt_modul_open_app(monkeypatch):
    routes = []
    monkeypatch.setattr(browser, "open_app", routes.append)
    assert browser.main(["--route", "/verlauf"]) == 0
    assert routes == ["/verlauf"]


def test_main_ende_zu_ende_mit_gemocktem_browser(monkeypatch):
    urls = []
    monkeypatch.setattr(browser.config, "load_config", dict)
    monkeypatch.setattr(browser, "connect_session", lambda cfg: {"port": 8712, "token": "tok"})
    monkeypatch.setattr(browser.webbrowser, "open", lambda url: urls.append(url) or True)
    assert browser.main(["--route", "/einstellungen?abschnitt=updates"]) == 0
    assert urls == ["http://127.0.0.1:8712/einstellungen?abschnitt=updates#t=tok"]


def test_main_kompakt_gibt_es_nicht_mehr(capsys):
    with pytest.raises(SystemExit):
        browser.main(["--compact"], opener=lambda route: pytest.fail("nichts öffnen"))


def test_main_fehler_exit_1_stderr_und_log(capsys):
    logged = []

    def failing(route):
        raise RuntimeError("Druckdienst startet nicht")

    assert browser.main([], opener=failing, log=logged.append) == 1
    assert "Druckdienst startet nicht" in capsys.readouterr().err
    assert logged == ["Tapesmith lässt sich nicht öffnen: Druckdienst startet nicht"]


def test_main_fehler_ohne_stderr_schreibt_app_log(monkeypatch):
    """pythonw bzw. Fenster-EXE: `sys.stderr` ist None, die Meldung landet in logs/app.log,
    nie in einem Meldungsfenster."""
    from tapesmith import paths

    monkeypatch.setattr(sys, "stderr", None)

    def failing(route):
        raise OSError("weg")

    assert browser.main([], opener=failing) == 1
    log = (paths.log_dir() / "app.log").read_text(encoding="utf-8")
    assert "FEHLER" in log and "weg" in log


def test_kein_meldungsfenster_mehr():
    assert not hasattr(browser, "error_box")
    assert "MessageBox" not in inspect.getsource(browser)


# ---------- Schnelldruck mit Zwischenablage (Tray-Kürzel) ----------

def test_quick_route_ohne_text():
    assert browser.quick_route() == ("/schnelldruck", False)
    assert browser.quick_route("  \r\n\t ") == ("/schnelldruck", False)


def test_quick_route_kodiert_und_vereinheitlicht():
    route, truncated = browser.quick_route(" a\r\nb&c#d?e=f\rü ")
    assert truncated is False
    assert route == "/schnelldruck?text=a%0Ab%26c%23d%3Fe%3Df%0A%C3%BC"
    assert browser.safe_route(route) == route
    parsed = urllib.parse.parse_qs(urllib.parse.urlsplit(route).query)
    assert parsed["text"] == ["a\nb&c#d?e=f\nü"]


def test_quick_route_entfernt_steuerzeichen():
    route, _ = browser.quick_route("A\x00B\x1bC\x7fD")
    assert route == "/schnelldruck?text=ABCD"


def test_quick_route_begrenzt_text_und_laenge():
    route, truncated = browser.quick_route("x" * 2000)
    assert truncated is True
    text = urllib.parse.parse_qs(urllib.parse.urlsplit(route).query)["text"][0]
    assert len(text) == browser.CLIP_TEXT_MAX
    # Mehrbyte-Zeichen: jedes wird zu 6 Zeichen kodiert, die Route bleibt trotzdem gültig
    route, truncated = browser.quick_route("€" * 500)
    assert truncated is True
    assert len(route) <= 2048
    assert browser.safe_route(route) == route


# ---------- Testmodus TAPESMITH_BROWSER_LOG ----------

def test_browser_log_ersetzt_dienst_und_browser(tmp_path, monkeypatch):
    log = tmp_path / "browser.log"
    monkeypatch.setenv("TAPESMITH_BROWSER_LOG", str(log))

    def nie(*a, **kw):
        raise AssertionError("im Testmodus weder Dienst noch Browser")

    monkeypatch.setattr(browser, "connect_session", nie)
    monkeypatch.setattr(browser, "default_opener", nie)
    assert browser.open_app("/schnelldruck?text=Hallo", config_loader=nie) == "/schnelldruck?text=Hallo"
    browser.open_app(None, config_loader=nie)
    assert log.read_text(encoding="utf-8").splitlines() == ["/schnelldruck?text=Hallo", "/schnelldruck"]


def test_browser_log_gilt_nicht_mit_eigenem_oeffner(tmp_path, monkeypatch):
    """Selbsttest und Tests mit eigenem Öffner laufen unverändert, auch wenn die Variable gesetzt ist."""
    monkeypatch.setenv("TAPESMITH_BROWSER_LOG", str(tmp_path / "browser.log"))
    opened = []
    url = browser.open_app("/verlauf", config_loader=dict,
                           connector=lambda cfg: {"port": 8712, "token": "t"}, opener=opened.append)
    assert url == opened[0] == "http://127.0.0.1:8712/verlauf#t=t"
    assert not (tmp_path / "browser.log").exists()


def test_browser_log_prueft_route_trotzdem(tmp_path, monkeypatch):
    monkeypatch.setenv("TAPESMITH_BROWSER_LOG", str(tmp_path / "browser.log"))
    with pytest.raises(ValueError):
        browser.open_app("//fremd")
    assert not (tmp_path / "browser.log").exists()


def test_modul_laedt_weder_qt_noch_fensterbibliothek():
    code = ("import sys, tapesmith.webui.browser; "
            "print(any(m in sys.modules for m in ('PySide6', 'webview', 'clr', 'pythonnet')))")
    env = dict(os.environ)
    src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                            env=env, timeout=60, check=True)
    assert result.stdout.strip() == "False"


def test_browser_quelltext_keine_gedankenstriche():
    quelltext = inspect.getsource(browser)
    assert "\u2013" not in quelltext
    assert "\u2014" not in quelltext
