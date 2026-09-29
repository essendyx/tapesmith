"""Tests für die Tray-App: Übersetzung von Menü und Meldungen (DE/EN, Sprachwechsel ohne Neustart),
Update-Hinweis im Menü, Live-Dunkelmodus. Nutzt dieselben Fakes wie `test_gui_tray.py`."""

import json
from types import SimpleNamespace

import pytest
from PySide6.QtGui import QPalette

from tapesmith import i18n, integration, paths
from tapesmith.gui import tray as tray_mod
from tapesmith.gui.hotkey import GERMAN_ALTGR, FakeLayoutProbe, HotkeyManager
from tapesmith.gui.theme import COLORS, COLORS_DARK
from tapesmith.gui.tray import TrayApp
from tapesmith.history import HistoryStore
from tapesmith.transport.base import ConnectTimeout
from test_gui_tray import NOW, P, FakeBackend, FakeHotkeyBackend, FakeIcon


@pytest.fixture
def env(qtbot, tmp_path):
    state = SimpleNamespace(cfg={}, backend=FakeBackend(), notes=[], routes=[], apps=[])

    def make(*, theme_reader=None, **kw):
        hotkeys = HotkeyManager(backend=FakeHotkeyBackend(), probe=FakeLayoutProbe(GERMAN_ALTGR))
        app = TrayApp(config_loader=lambda: json.loads(json.dumps(state.cfg)),
                      profile_loader=lambda: P,
                      backend_factory=lambda cfg, profile: state.backend,
                      history_factory=lambda: HistoryStore(tmp_path / "verlauf.sqlite3"),
                      hotkeys=hotkeys,
                      tray_icon_factory=lambda parent: FakeIcon(parent),
                      clipboard_reader=lambda: None,
                      browser_opener=lambda route: state.routes.append(route),
                      config_stamp_reader=lambda: 1,
                      registry_factory=lambda: integration.FakeRegistry(),
                      notify=lambda title, text: state.notes.append(f"{title}: {text}"),
                      now=lambda: NOW, theme_reader=theme_reader, **kw)
        state.apps.append(app)
        app.start()
        qtbot.waitUntil(lambda: not app.backend_pending(), timeout=5000)
        return app

    state.make = make
    yield state
    for app in state.apps:
        app.stop()


# ---------- Übersetzung ----------

def test_menu_englisch(env):
    env.cfg = {"app": {"language": "en"}}
    app = env.make()
    actions = app.menu_actions()
    assert actions["trayQuick"].text().startswith("Quick print")
    assert actions["trayClipboard"].text().startswith("Clipboard to quick print")
    assert actions["trayMain"].text() == "Open web interface"
    assert actions["trayHistory"].text() == "History"
    assert actions["traySettings"].text() == "Settings"
    assert actions["trayQuit"].text() == "Quit"


def test_menu_deutsch_standard(env):
    app = env.make()
    actions = app.menu_actions()
    assert actions["trayQuick"].text().startswith("Schnelldruck")
    assert actions["trayMain"].text() == "Web-Oberfläche öffnen"


def test_menue_texte_ohne_auslassungspunkte(env):
    """Kein Menüeintrag kündigt ein Fenster an („…“): alles öffnet einen Browser-Tab."""
    app = env.make()
    texts = [a.text() for a in app.menu_actions().values()]
    assert not [t for t in texts if "…" in t or "..." in t]


def test_sprachwechsel_ohne_neustart_beim_oeffnen_des_menues(env):
    app = env.make()
    assert app.menu_actions()["trayMain"].text() == "Web-Oberfläche öffnen"
    env.cfg = {"app": {"language": "en"}}
    app._on_menu_show()
    assert app.menu_actions()["trayMain"].text() == "Open web interface"


def test_apply_settings_uebersetzt_menue(env):
    app = env.make()
    env.cfg = {"app": {"language": "en"}}
    app.apply_settings()
    assert app.menu_actions()["trayQuick"].text().startswith("Quick print")
    assert app.menu_actions()["trayQuit"].text() == "Quit"


def test_fehlermeldung_englischer_titel_aus_katalog(env):
    env.cfg = {"app": {"language": "en"}}
    app = env.make()
    text = app._error_text(ConnectTimeout("weg"))
    assert text.startswith(i18n.tr("errors.printer.unreachable.title", "en"))
    assert i18n.tr("errors.printer.unreachable.hint", "en") in text


def test_fehlermeldung_deutscher_titel_wie_bisher(env):
    app = env.make()
    text = app._error_text(ConnectTimeout("weg"))
    assert text.startswith("Drucker nicht erreichbar")


# ---------- Update-Hinweis ----------

def test_update_hinweis_ohne_datei(env, qtbot):
    app = env.make()
    action = app.menu_actions()["trayUpdate"]
    assert action.text() == i18n.tr("tray.menu.updateCheck", "de")
    action.trigger()
    qtbot.waitUntil(lambda: env.routes == ["/einstellungen?abschnitt=updates"])


def test_update_hinweis_mit_verfuegbarer_version(env, qtbot):
    update_dir = paths.app_dir() / "update"
    update_dir.mkdir(parents=True, exist_ok=True)
    (update_dir / "state.json").write_text(
        json.dumps({"installed": True, "available": {"version": "0.2.1"}}), encoding="utf-8")
    app = env.make()
    action = app.menu_actions()["trayUpdate"]
    assert "0.2.1" in action.text()
    action.trigger()
    qtbot.waitUntil(lambda: env.routes == ["/einstellungen?abschnitt=updates"])


def test_update_hinweis_kaputte_datei_faellt_zurueck(env):
    update_dir = paths.app_dir() / "update"
    update_dir.mkdir(parents=True, exist_ok=True)
    (update_dir / "state.json").write_text("{kaputt", encoding="utf-8")
    app = env.make()
    action = app.menu_actions()["trayUpdate"]
    assert action.text() == i18n.tr("tray.menu.updateCheck", "de")


def test_update_hinweis_nicht_installiert_zeigt_check(env):
    update_dir = paths.app_dir() / "update"
    update_dir.mkdir(parents=True, exist_ok=True)
    (update_dir / "state.json").write_text(
        json.dumps({"installed": False, "available": {"version": "0.2.1"}}), encoding="utf-8")
    app = env.make()
    action = app.menu_actions()["trayUpdate"]
    assert action.text() == i18n.tr("tray.menu.updateCheck", "de")


# ---------- Live-Dunkelmodus ----------

def test_live_dunkelmodus_wechsel(env, monkeypatch, qapp):
    reader_value = {"value": 1}   # hell (AppsUseLightTheme=1)
    app = env.make(theme_reader=lambda: reader_value["value"])
    assert app._dark is False

    calls = []
    original = tray_mod.make_icon

    def spy(role, *, dark_taskbar=None):
        calls.append(dark_taskbar)
        return original(role, dark_taskbar=dark_taskbar)

    monkeypatch.setattr(tray_mod, "make_icon", spy)
    try:
        reader_value["value"] = 0   # dunkel
        app._check_theme()
        assert app._dark is True
        assert calls[-1] is True
        assert qapp.palette().color(QPalette.ColorRole.Window).name().lower() == COLORS_DARK["window"].lower()

        reader_value["value"] = 1   # zurück auf hell
        app._check_theme()
        assert app._dark is False
        assert calls[-1] is False
        assert qapp.palette().color(QPalette.ColorRole.Window).name().lower() == COLORS["window"].lower()
    finally:
        from tapesmith.gui.theme import apply_theme

        apply_theme(qapp, dark=False)


def test_check_theme_ohne_aenderung_bleibt_unveraendert(env):
    app = env.make(theme_reader=lambda: 1)
    before = app._dark
    app._check_theme()
    assert app._dark == before is False
