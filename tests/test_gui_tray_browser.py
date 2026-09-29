"""Tests für die Verdrahtung der Tray-App: „Öffnen“, Schnelldruck (Menü und Hotkey) und Favoriten
öffnen die Web-Oberfläche im Standardbrowser (gemockt), nie ein Fenster; der eigene Start wartet
nicht synchron auf das Druck-Backend. Nutzt die Fakes aus `test_gui_tray.py` (kein echter Druck, keine echten
Prozesse, kein echtes Infobereich-Symbol)."""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from tapesmith import i18n, integration
from tapesmith.gui.hotkey import GERMAN_ALTGR, FakeLayoutProbe, HotkeyManager
from tapesmith.gui.tray import TrayApp
from tapesmith.history import HistoryStore
from test_gui_tray import NOW, P, FakeBackend, FakeHotkeyBackend, FakeIcon

# `CONNECTING_NOTICE` kommt jetzt aus dem Übersetzungskatalog (`tray.notify.connecting`)
# statt aus einer Modulkonstante.
CONNECTING_NOTICE = i18n.tr("tray.notify.connecting", "de")


@pytest.fixture
def env(qtbot, tmp_path):
    state = SimpleNamespace(cfg={}, backend=FakeBackend(), notes=[], routes=[], apps=[], hotkeys=None)

    def make(*, gate: threading.Event | None = None, **kw):
        kw.setdefault("browser_opener", lambda route: state.routes.append(route))
        hotkeys = HotkeyManager(backend=FakeHotkeyBackend(), probe=FakeLayoutProbe(GERMAN_ALTGR))

        def factory(cfg, profile):
            if gate is not None:
                gate.wait(5.0)
            return state.backend

        app = TrayApp(config_loader=lambda: dict(state.cfg),
                      profile_loader=lambda: P,
                      backend_factory=factory,
                      history_factory=lambda: HistoryStore(tmp_path / "verlauf.sqlite3"),
                      hotkeys=hotkeys,
                      tray_icon_factory=lambda parent: FakeIcon(parent),
                      clipboard_reader=lambda: None,
                      config_stamp_reader=lambda: 1,
                      registry_factory=lambda: integration.FakeRegistry(),
                      notify=lambda title, text: state.notes.append(f"{title}: {text}"),
                      now=lambda: NOW, **kw)
        state.apps.append(app)
        state.hotkeys = hotkeys
        return app

    state.make = make
    yield state
    for app in state.apps:
        app.stop()


def notes_text(env):
    return "\n".join(env.notes)


# ---------- Öffnen, Hotkey, Favoriten ----------

def test_oeffnen_oeffnet_browser(env, qtbot):
    app = env.make()
    app.start()
    qtbot.waitUntil(lambda: not app.backend_pending(), timeout=5000)
    app.menu_actions()["trayMain"].trigger()
    qtbot.waitUntil(lambda: env.routes == [None])


def test_oeffnen_standard_ruft_open_app_mit_tray_konfiguration(env, qtbot, monkeypatch):
    """Ohne eigenen Öffner nutzt die Tray-App `webui.browser.open_app` mit ihrem config_loader."""
    from tapesmith.webui import browser

    calls = []
    monkeypatch.setattr(browser, "open_app",
                        lambda route, *, config_loader: calls.append((route, config_loader())) or "url")
    env.cfg = {"web": {"port": 8799}}
    app = env.make(browser_opener=None)
    app.open_web("/verlauf")
    qtbot.waitUntil(lambda: len(calls) == 1)
    assert calls == [("/verlauf", {"web": {"port": 8799}})]


def test_oeffnen_fehler_meldet_benachrichtigung(env, qtbot):
    def failing(route):
        raise RuntimeError("Druckdienst startet nicht")

    app = env.make(browser_opener=failing)
    app.open_app_window()
    qtbot.waitUntil(lambda: "Druckdienst startet nicht" in notes_text(env))
    assert i18n.tr("tray.notify.openFailed.title", "de") in notes_text(env)


def test_oeffnen_friert_das_tray_nicht_ein(env, qtbot):
    """Dienststart und Browseraufruf laufen im Hintergrund: `open_web` kehrt sofort zurück."""
    gate = threading.Event()
    started = threading.Event()

    def slow(route):
        started.set()
        gate.wait(5.0)

    app = env.make(browser_opener=slow)
    app.open_web("/verlauf")
    assert started.wait(5.0)
    gate.set()


def test_hotkey_schnelldruck_oeffnet_browser(env, qtbot):
    app = env.make()
    app.start()
    qtbot.waitUntil(lambda: not app.backend_pending(), timeout=5000)
    env.hotkeys.triggered.emit("quick")
    qtbot.waitUntil(lambda: env.routes == ["/schnelldruck"])


def test_menue_schnelldruck_oeffnet_browser(env, qtbot):
    app = env.make()
    app.start()
    app.menu_actions()["trayQuick"].trigger()
    qtbot.waitUntil(lambda: env.routes == ["/schnelldruck"])


def test_favorit_mit_fehlendem_feld_oeffnet_browser_mit_uri(env, qtbot):
    env.cfg = {"tray": {"favorites": [{"title": "Platte", "template": "datentraeger",
                                       "values": {"host": "pmx20"}}]}}
    app = env.make()
    app.start()
    qtbot.waitUntil(lambda: not app.backend_pending(), timeout=5000)
    app.print_favorite(0)
    qtbot.waitUntil(lambda: len(env.routes) == 1)
    assert env.routes[0].startswith("/aktion?uri=tapesmith%3A%2F%2Fprint")


# ---------- Asynchroner Start ----------

def test_start_kehrt_zurueck_bevor_backend_fertig_ist(env, qtbot):
    gate = threading.Event()
    app = env.make(gate=gate)

    app.start()

    assert app.backend_pending() is True
    assert app.backend is None
    assert "verbinde" in app.tooltip()

    gate.set()
    qtbot.waitUntil(lambda: not app.backend_pending(), timeout=5000)

    assert app.backend is env.backend
    assert env.backend.listeners.keys() >= {"state", "status", "progress", "queue"}
    assert "verbinde" not in app.tooltip()


def test_druck_waehrend_verbindung_meldet_hinweis_ohne_absturz(env, qtbot):
    gate = threading.Event()
    app = env.make(gate=gate)
    app.start()

    app.print_test_label()

    assert CONNECTING_NOTICE in notes_text(env)
    assert env.backend.requests == []

    gate.set()
    qtbot.waitUntil(lambda: not app.backend_pending(), timeout=5000)


def test_stop_waehrend_verbindung_schliesst_verworfenes_backend(env, qtbot):
    gate = threading.Event()
    app = env.make(gate=gate)
    app.start()

    app.stop()
    assert not env.backend.closed

    gate.set()
    qtbot.waitUntil(lambda: env.backend.closed, timeout=5000)


def test_tray_start_methoden_ohne_gedankenstriche():
    import inspect

    for methode in (TrayApp.start, TrayApp._connect_backend, TrayApp._on_backend_ready):
        quelltext = inspect.getsource(methode)
        assert "\u2013" not in quelltext, methode.__name__
        assert "\u2014" not in quelltext, methode.__name__


def test_tray_submit_meldung_ohne_gedankenstrich():
    import inspect

    quelltext = inspect.getsource(TrayApp.submit)
    assert "\u2013" not in quelltext
    assert "\u2014" not in quelltext
