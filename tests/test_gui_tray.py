"""Tests für die Tray-App: Menü, Hotkeys, Browser-Tabs statt Fenster (Schnelldruck,
Zwischenablage, Verlauf, Einstellungen), Favoriten mit zentralen Zählern, Nachdruck,
Warteschlange, Autostart, Status-Tooltip, Konfigurations-Neuladen und Einzelinstanz.

Alles über Fakes: kein echtes Tastenkürzel, keine echte Zwischenablage, keine Prozesse, keine
Registry (FakeRegistry), kein Druck (Fake-Backend), kein echtes Infobereich-Symbol."""

import json
import threading
from datetime import datetime
from types import SimpleNamespace
from urllib.parse import parse_qs, unquote, urlsplit

import pytest
from PIL import Image
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from tapesmith import integration, paths
from tapesmith.daemon.instance import SingleInstance
from tapesmith.device.profile import load_profile
from tapesmith.gui import tray as tray_mod
from tapesmith.gui.hotkey import GERMAN_ALTGR, FakeLayoutProbe, HotkeyManager, parse_hotkey
from tapesmith.gui.tray import TrayApp
from tapesmith.history import HistoryStore
from tapesmith.ipc.backend import local_planner
from tapesmith.ipc.codec import StateInfo, StatusReport
from tapesmith.ipc.pipe import home_key
from tapesmith.jobs import JobMeta
from tapesmith.pipeline import PrintOutcome
from tapesmith.printer import PrintResult

P = load_profile()
NOW = datetime(2026, 9, 27, 10, 30)

MENU_NAMES = ("trayUpdate", "trayMain", "trayQuick", "trayClipboard", "trayFavorites", "trayRecent",
              "trayTest", "trayHistory", "trayQueuePause", "trayStatus", "trayLog", "traySettings",
              "trayAutostart", "trayQuit")


class FakeHotkeyBackend:
    def __init__(self):
        self.registered = {}
        self.hwnds = []

    def register(self, hwnd, hotkey_id, modifiers, vk):
        self.registered[hotkey_id] = (modifiers, vk)
        self.hwnds.append(hwnd)
        return True

    def unregister(self, hwnd, hotkey_id):
        self.registered.pop(hotkey_id, None)


class FakeQueueOps:
    def __init__(self):
        self.calls = []

    def pause(self):
        self.calls.append("pause")

    def resume(self):
        self.calls.append("resume")

    def list(self, include_done=False):
        return SimpleNamespace(paused=False, jobs=())


class FakeBackend:
    kind = "daemon"
    fallback_reason = ""

    def __init__(self, statuses=("ok",), with_queue=True):
        self.statuses = list(statuses)
        self.requests = []
        self.enqueue = []
        self.listeners = {}
        self.ops = FakeQueueOps() if with_queue else None
        self.closed = False
        self.status_calls = []
        self.lock = threading.Lock()

    def plan(self, request):
        return local_planner({}, P)(request)

    def execute(self, request, *, cancel=None, on_progress=None, on_warning=None, on_cut_pause=None,
                enqueue_on_offline=False):
        with self.lock:
            self.requests.append(request)
            self.enqueue.append(enqueue_on_offline)
            status = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
        plan = self.plan(request)
        if status == "ok":
            return PrintOutcome("ok", plan, results=[PrintResult(80, [], 0.1, "ok", 80)], history_id=3)
        if status == "wartet":
            return PrintOutcome("wartet", plan, queue_id=4)
        if status == "bestätigung_nötig":
            return PrintOutcome(status, plan, reasons=("Label länger als 200 mm",))
        if status == "fehler":
            raise RuntimeError("Drucker weg")
        return PrintOutcome(status, plan, reasons=("Kontingent erschöpft",))

    def state_info(self):
        return StateInfo("getrennt")

    def query_status(self, *, quick=False, fresh=True):
        self.status_calls.append(fresh)
        return StatusReport(StateInfo("verbunden", "COM4"), None, NOW)

    def add_listener(self, event, callback):
        self.listeners.setdefault(event, []).append(callback)

    def remove_listener(self, event, callback):
        self.listeners.get(event, []).remove(callback)

    def queue_ops(self):
        return self.ops

    def close(self):
        self.closed = True

    def fire(self, event, data):
        for callback in list(self.listeners.get(event, [])):
            callback(data)


class FakeIcon(QSystemTrayIcon):
    def show(self):
        pass

    def hide(self):
        pass


@pytest.fixture
def env(qtbot, tmp_path):
    state = SimpleNamespace(cfg={}, backend=FakeBackend(), notes=[], routes=[],
                            clipboard="", reg=integration.FakeRegistry(), stamp=1,
                            hotkey_backend=FakeHotkeyBackend(), apps=[])

    def make(**kw):
        hotkeys = HotkeyManager(backend=state.hotkey_backend, probe=FakeLayoutProbe(GERMAN_ALTGR))
        app = TrayApp(config_loader=lambda: json.loads(json.dumps(state.cfg)),
                      profile_loader=lambda: P,
                      backend_factory=lambda cfg, profile: state.backend,
                      history_factory=lambda: HistoryStore(tmp_path / "verlauf.sqlite3"),
                      hotkeys=hotkeys,
                      tray_icon_factory=lambda parent: FakeIcon(parent),
                      clipboard_reader=lambda: state.clipboard,
                      browser_opener=lambda route: state.routes.append(route),
                      config_stamp_reader=lambda: state.stamp,
                      registry_factory=lambda: state.reg,
                      notify=lambda title, text: state.notes.append(f"{title}: {text}"),
                      now=lambda: NOW, **kw)
        state.apps.append(app)
        app.start()
        # Das Backend entsteht asynchron (BackgroundCall); die bestehenden Tests hier
        # gehen weiter vom alten, synchronen Ablauf aus, deshalb hier einmal auf das Ergebnis
        # warten (schnelles Fake-Backend, dauert praktisch nicht).
        qtbot.waitUntil(lambda: not app.backend_pending(), timeout=5000)
        state.hotkeys = hotkeys
        return app

    state.make = make
    yield state
    for app in state.apps:
        app.stop()


def wait_idle(qtbot, app):
    qtbot.waitUntil(lambda: not app.busy(), timeout=5000)


def notes_text(env):
    return "\n".join(env.notes)


def visible_windows():
    """Alle sichtbaren Qt-Fenster der Anwendung (die Tray-App darf keines haben)."""
    return [w for w in QApplication.topLevelWidgets() if w.isVisible()]


# ---------- 11: Start ----------

def test_start_baut_menue_und_registriert_hotkeys(env):
    app = env.make()
    actions = app.menu_actions()
    for name in MENU_NAMES:
        assert name in actions, name
    assert actions["trayQuick"].text() == "Schnelldruck (Strg+Alt+L)"
    assert actions["trayClipboard"].text() == "Zwischenablage in Schnelldruck (Strg+Alt+Umschalt+L)"
    assert "Keine Favoriten (Einstellungen, Tray und Tastenkürzel)" in [
        a.text() for a in actions["trayFavorites"].menu().actions()]
    assert not actions["trayFavorites"].menu().actions()[0].isEnabled()
    assert env.hotkeys.registered() == {"quick": parse_hotkey("Ctrl+Alt+L"),
                                        "clipboard": parse_hotkey("Ctrl+Alt+Shift+L")}
    assert len(env.hotkey_backend.registered) == 2
    # ohne Fenster registriert: hwnd 0 (RegisterHotKey mit NULL, Thread-Nachricht)
    assert env.hotkey_backend.hwnds == [0, 0]
    assert visible_windows() == []
    assert env.notes == []
    assert env.backend.listeners.keys() >= {"state", "status", "progress", "queue"}
    app.stop()
    assert env.hotkey_backend.registered == {}
    assert env.backend.closed


def test_start_altgr_konflikt_benachrichtigt(env):
    env.cfg = {"hotkey": {"quick": "Ctrl+Alt+Q"}}
    app = env.make()
    assert "@" in notes_text(env)
    assert list(env.hotkeys.registered()) == ["clipboard"]
    assert app.menu_actions()["trayQuick"].text() == "Schnelldruck"


def test_start_ohne_hotkeys(env):
    env.cfg = {"hotkey": {"enabled": False}}
    env.make()
    assert env.hotkeys.registered() == {}


# ---------- 12: Schnelldruck im Browser ----------

def test_hotkey_quick_oeffnet_schnelldruck_im_browser(env, qtbot):
    app = env.make()
    env.hotkeys.triggered.emit("quick")
    qtbot.waitUntil(lambda: env.routes == ["/schnelldruck"])
    assert env.backend.requests == []
    assert visible_windows() == []
    assert not hasattr(app, "quick_popup")


def test_linksklick_oeffnet_web_oberflaeche(env, qtbot):
    app = env.make()
    app.tray_icon.activated.emit(QSystemTrayIcon.ActivationReason.Trigger)
    qtbot.waitUntil(lambda: env.routes == [None])
    assert visible_windows() == []


def test_linksklick_alte_einstellung_web_oeffnet_browser(env, qtbot):
    """Auch eine alte config.json mit `app.quick_window` öffnet nur den Browser, nie ein Fenster."""
    env.cfg = {"app": {"quick_window": "web"}}
    app = env.make()
    app.tray_icon.activated.emit(QSystemTrayIcon.ActivationReason.Trigger)
    qtbot.waitUntil(lambda: env.routes == [None])
    assert visible_windows() == []


def test_ohne_warteschlange_kein_enqueue(env, qtbot):
    env.cfg = {"queue": {"enabled": False}}
    app = env.make()
    app.print_test_label()
    wait_idle(qtbot, app)
    assert env.backend.enqueue == [False]
    assert env.backend.requests[0].meta.source == "hotkey"
    assert "Test 27.09.2026 10:30" in env.backend.requests[0].meta.title


def test_gedruckt_benachrichtigung_abschaltbar(env, qtbot):
    env.cfg = {"tray": {"notify": False}}
    app = env.make()
    app.print_test_label()
    wait_idle(qtbot, app)
    assert env.notes == []


def test_fehler_im_klartext(env, qtbot):
    env.backend.statuses = ["fehler"]
    app = env.make()
    app.print_test_label()
    wait_idle(qtbot, app)
    qtbot.waitUntil(lambda: "Drucker weg" in notes_text(env))


# ---------- 13: Zwischenablage in den Schnelldruck ----------

def _text_of(route):
    parts = urlsplit(route)
    assert parts.path == "/schnelldruck"
    return parse_qs(parts.query)["text"][0]


def test_zwischenablage_oeffnet_schnelldruck_vorbelegt(env, qtbot):
    env.clipboard = "S4EWNX0R123456\r\nZeile 2 & mehr"
    app = env.make()
    env.hotkeys.triggered.emit("clipboard")
    qtbot.waitUntil(lambda: len(env.routes) == 1)
    assert _text_of(env.routes[0]) == "S4EWNX0R123456\nZeile 2 & mehr"
    assert " " not in env.routes[0] and "&mehr" not in env.routes[0]
    assert env.backend.requests == []        # nie Direktdruck
    assert visible_windows() == []
    assert env.notes == []
    assert not hasattr(app, "clip_toast")


def test_zwischenablage_menue_wie_kuerzel(env, qtbot):
    env.clipboard = "Hallo"
    app = env.make()
    app.menu_actions()["trayClipboard"].trigger()
    qtbot.waitUntil(lambda: env.routes == ["/schnelldruck?text=Hallo"])


def test_zwischenablage_leer(env):
    env.clipboard = "  \n "
    app = env.make()
    app.open_clipboard()
    assert "Zwischenablage ohne Text" in notes_text(env)
    assert env.routes == []


def test_zwischenablage_ohne_text(env):
    env.clipboard = None
    app = env.make()
    app.open_clipboard()
    assert "Zwischenablage ohne Text" in notes_text(env)
    assert env.routes == []


def test_zwischenablage_lang_wird_gekuerzt(env, qtbot):
    env.clipboard = "ä" * 5000
    app = env.make()
    app.open_clipboard()
    qtbot.waitUntil(lambda: len(env.routes) == 1)
    route = env.routes[0]
    assert len(route) <= 2048
    assert 0 < len(_text_of(route)) <= tray_mod.browser.CLIP_TEXT_MAX
    assert "gekürzt" in notes_text(env)


def test_zwischenablage_nicht_lesbar(env):
    app = env.make()

    def broken():
        raise RuntimeError("gesperrt")

    app._clipboard_reader = broken
    app.open_clipboard()
    assert "gesperrt" in notes_text(env)
    assert env.routes == []


# ---------- 14: Favoriten ----------

def test_favorit_druckt(env, qtbot):
    env.cfg = {"tray": {"favorites": [{"title": "Geöffnet am", "template": "geoeffnet-am", "values": {}}]}}
    app = env.make()
    action = app.menu_actions()["trayFavorite0"]
    assert action.text() == "Geöffnet am"
    action.trigger()
    wait_idle(qtbot, app)
    assert len(env.backend.requests) == 1
    meta = env.backend.requests[0].meta
    assert meta.template == "geoeffnet-am"
    assert meta.source == "hotkey"
    assert "27.09.2026" in meta.title


def test_favorit_mit_fehlendem_feld_oeffnet_browser(env, qtbot):
    env.cfg = {"tray": {"favorites": [{"title": "Platte", "template": "datentraeger",
                                       "values": {"host": "pmx20"}}]}}
    app = env.make()
    app.print_favorite(0)
    assert env.backend.requests == []
    qtbot.waitUntil(lambda: len(env.routes) == 1)
    route = env.routes[0]
    assert route.startswith("/aktion?uri=")
    uri = unquote(route.split("uri=", 1)[1])
    assert uri.startswith("tapesmith://print?template=datentraeger")
    assert "host=pmx20" in uri
    assert integration.parse_uri(uri).values == {"host": "pmx20"}


def test_favoriten_ausgeschalteter_module_ausgeblendet(env, qtbot):
    env.cfg = {"modules": {"enabled": []},
               "tray": {"favorites": [{"title": "Platte", "template": "datentraeger"},
                                      {"title": "Geöffnet am", "template": "geoeffnet-am"}]}}
    app = env.make()
    actions = app.menu_actions()
    assert actions["trayFavorite0"].text() == "Geöffnet am"
    assert "trayFavorite1" not in actions


def _counter_template(tmp_path):
    path = tmp_path / "zaehler.tapesmith.json"
    path.write_text(json.dumps({
        "schema_version": 2, "name": "zaehler", "description": "Test",
        "fields": [{"id": "nr", "label": "Nummer", "type": "counter", "format": "ASN{:05d}"}],
        "layout": {"lines": ["{nr}"]},
    }), encoding="utf-8")
    return path


def test_favorit_zentrale_zaehler(env, qtbot, tmp_path):
    central = tmp_path / "zentral"
    env.cfg = {"numbering": {"dir": str(central)},
               "tray": {"favorites": [{"title": "Nächste ASN", "template": str(_counter_template(tmp_path)),
                                       "values": {}}]}}
    env.backend.statuses = ["ok", "wartet", "abgelehnt", "fehler", "ok"]
    app = env.make()
    titles = []
    for _ in range(5):
        app.print_favorite(0)
        wait_idle(qtbot, app)
        titles.append(env.backend.requests[-1].meta.title)
    # ok -> commit, wartet -> commit (Nummer vergeben), abgelehnt/Fehler -> kein Commit
    assert titles == ["ASN00001", "ASN00002", "ASN00003", "ASN00003", "ASN00003"]
    counters = json.loads((central / "counters.json").read_text(encoding="utf-8"))
    assert counters == {"zaehler.nr": 3}
    assert not (paths.app_dir() / "counters.json").exists()
    assert app.counters().path == central / "counters.json"


# ---------- 15: Letzte Labels ----------

def _record(history, title, *, sensitive=False, status="ok"):
    head = Image.new("1", (P.head_dots, 60), 255)
    meta = JobMeta(source="gui", kind="text", title=title, sensitive=sensitive)
    return history.record(meta, landscape=None, head=head, length_mm=7.5, tape_mm=30.0, status=status)


def test_letzte_labels(env, qtbot, tmp_path):
    with HistoryStore(tmp_path / "verlauf.sqlite3") as history:
        ids = [_record(history, f"Label {i}") for i in range(6)]
        _record(history, "Geheim", sensitive=True)
        _record(history, "Kaputt", status="fehler")
    app = env.make()
    entries = app.recent_entries()
    assert [e.id for e in entries] == list(reversed(ids))[:5]
    app.rebuild_recent_menu()
    menu = app.menu_actions()["trayRecent"].menu()
    texts = [a.text() for a in menu.actions()]
    assert len(texts) == 5
    assert not any("Geheim" in t or "Kaputt" in t for t in texts)
    menu.actions()[0].trigger()
    wait_idle(qtbot, app)
    assert len(env.backend.requests) == 1
    meta = env.backend.requests[0].meta
    assert meta.kind == "reprint"
    assert meta.source == "hotkey"


def test_letzte_labels_leer(env):
    app = env.make()
    menu = app.menu_actions()["trayRecent"].menu()
    assert len(menu.actions()) == 1
    assert not menu.actions()[0].isEnabled()


# ---------- 16: Warteschlange, Hauptfenster, Log, Autostart ----------

def test_warteschlange_pausieren(env):
    app = env.make()
    action = app.menu_actions()["trayQueuePause"]
    assert action.isEnabled() and action.isCheckable()
    action.trigger()
    assert env.backend.ops.calls == ["pause"]
    assert action.isChecked()
    action.trigger()
    assert env.backend.ops.calls == ["pause", "resume"]
    assert not action.isChecked()


def test_warteschlange_ohne_dienst_deaktiviert(env):
    env.backend = FakeBackend(with_queue=False)
    app = env.make()
    assert not app.menu_actions()["trayQueuePause"].isEnabled()
    app.toggle_queue_pause()   # darf nichts tun


@pytest.mark.parametrize("name, route", [
    ("trayMain", None),
    ("trayQuick", "/schnelldruck"),
    ("trayHistory", "/verlauf"),
    ("trayStatus", "/einstellungen?abschnitt=verbindung"),
    ("trayLog", "/protokoll"),
    ("traySettings", "/einstellungen?abschnitt=tray"),
    ("trayUpdate", "/einstellungen?abschnitt=updates"),
])
def test_menue_oeffnet_browser_tab(env, qtbot, name, route):
    app = env.make()
    app.menu_actions()[name].trigger()
    qtbot.waitUntil(lambda: env.routes == [route])
    assert visible_windows() == []


def test_autostart(env):
    app = env.make()
    actions = app.menu_actions()
    assert not app.autostart_enabled()
    assert not actions["trayAutostart"].isChecked()
    actions["trayAutostart"].trigger()
    assert env.reg.get(integration.RUN_KEY, integration.RUN_VALUE) is not None
    assert app.autostart_enabled()
    assert actions["trayAutostart"].isChecked()
    actions["trayAutostart"].trigger()
    assert env.reg.get(integration.RUN_KEY, integration.RUN_VALUE) is None
    assert not app.autostart_enabled()


def test_browser_fehler_als_benachrichtigung(env, qtbot):
    app = env.make()

    def fail(route):
        raise RuntimeError("Dienst aus")

    app._browser_opener = fail
    app.open_quick()
    qtbot.waitUntil(lambda: "Dienst aus" in notes_text(env))
    assert visible_windows() == []


# ---------- 17: Status ----------

def test_status_tooltip_und_fortschritt(env, qtbot):
    app = env.make()
    tips = []
    app.statusUpdated.connect(tips.append)
    env.backend.fire("state", StateInfo("verbunden", "COM4"))
    qtbot.waitUntil(lambda: "verbunden (COM4)" in app.tooltip())
    assert tips and "verbunden (COM4)" in tips[-1]
    assert app.tray_icon.toolTip() == app.tooltip()
    env.backend.fire("progress", {"job_key": "x", "done": 45, "total": 100})
    qtbot.waitUntil(lambda: "Druckt … 45 %" in app.tooltip())
    env.backend.fire("progress", {"job_key": "x", "done": 100, "total": 100})
    qtbot.waitUntil(lambda: "Druckt" not in app.tooltip())


def test_version_in_menue_und_tooltip(env):
    from tapesmith import __version__

    app = env.make()
    version = app.menu_actions()["trayVersion"]
    assert version.text() == f"Tapesmith {__version__}"
    assert not version.isEnabled()
    assert app._menu.actions()[0] is version
    assert app.tooltip().splitlines()[0] == f"Tapesmith {__version__}"
    assert len(app.tooltip()) <= 127


def test_status_abfragen(env, qtbot):
    app = env.make()
    app.query_status()
    qtbot.waitUntil(lambda: env.backend.status_calls == [True])
    qtbot.waitUntil(lambda: "verbunden (COM4)" in app.tooltip())


# ---------- 18: Rückfrage ----------

def test_bestaetigung_noetig_kein_zweiter_druck(env, qtbot):
    env.backend.statuses = ["bestätigung_nötig"]
    app = env.make()
    app.print_test_label()
    wait_idle(qtbot, app)
    qtbot.waitUntil(lambda: "200 mm" in notes_text(env))
    assert len(env.backend.requests) == 1


# ---------- Einstellungen aus der Web-Oberfläche ohne Neustart ----------

def test_einstellungen_neu_anwenden(env):
    app = env.make()
    env.cfg = {"hotkey": {"quick": "Ctrl+Alt+K", "clipboard": "Win+Shift+F9"}}
    app.apply_settings()
    assert env.hotkeys.registered()["quick"] == parse_hotkey("Ctrl+Alt+K")
    assert env.hotkeys.registered()["clipboard"] == parse_hotkey("Win+Shift+F9")
    assert len(env.hotkey_backend.registered) == 2
    assert app.menu_actions()["trayQuick"].text() == "Schnelldruck (Strg+Alt+K)"


def test_konfig_aenderung_wird_ohne_neustart_uebernommen(env):
    app = env.make()
    calls = len(env.hotkey_backend.hwnds)
    assert app.check_config() is False            # Datei unverändert: nichts tun
    env.cfg = {"hotkey": {"quick": "Ctrl+Alt+K"}, "app": {"language": "en"}}
    env.stamp = 2
    assert app.check_config() is True
    assert env.hotkeys.registered()["quick"] == parse_hotkey("Ctrl+Alt+K")
    assert app.menu_actions()["trayQuick"].text() == "Quick print (Strg+Alt+K)"
    assert len(env.hotkey_backend.hwnds) == calls + 2


def test_konfig_ohne_kuerzel_aenderung_registriert_nicht_neu(env):
    app = env.make()
    calls = len(env.hotkey_backend.hwnds)
    env.cfg = {"tray": {"notify": False}}
    env.stamp = 3
    assert app.check_config() is True
    assert len(env.hotkey_backend.hwnds) == calls


def test_konfig_abschalten_und_kaputt(env):
    app = env.make()
    env.cfg = {"hotkey": {"enabled": False}}
    env.stamp = 4
    app.check_config()
    assert env.hotkeys.registered() == {}
    app._config_loader = lambda: (_ for _ in ()).throw(ValueError("config.json kaputt"))
    env.stamp = 5
    assert app.check_config() is True
    assert "kaputt" in notes_text(env)


# ---------- 19: Einzelinstanz ----------

def test_main_zweite_instanz_beendet_sich(monkeypatch):
    holder = SingleInstance(f"Local\\Tapesmith.Tray.{home_key()}")
    assert holder.acquire()

    def no_app(*args, **kwargs):
        raise AssertionError("QApplication darf nicht starten")

    monkeypatch.setattr(tray_mod, "QApplication", no_app)
    try:
        assert tray_mod.main(["--no-hotkeys"]) == 0
    finally:
        holder.release()


# ---------- Dienst-Neustart: Hotkey druckt nach `tapesmith daemon restart` weiter ----------

def test_druck_nach_dienst_neustart(env, qtbot):
    from ipc_fakes import RestartableDaemon
    from tapesmith.ipc.backend import make_backend

    daemon = RestartableDaemon()
    try:
        env.backend = make_backend({"daemon": {"spawn": False}}, P, client="tray",
                                   local_factory=lambda reason: FakeBackend(), env={},
                                   connector=daemon.connector)
        app = env.make()
        first = daemon.current
        app.print_test_label()
        wait_idle(qtbot, app)
        old_client = app.backend.client
        second = daemon.restart()
        qtbot.waitUntil(lambda: old_client.closed, timeout=3000)
        app.print_test_label()
        wait_idle(qtbot, app)
        assert len(first.calls("print")) == 1
        assert len(second.calls("print")) == 1
        assert app.backend.kind == "daemon"
        assert "verloren" not in notes_text(env) and "Nicht gedruckt" not in notes_text(env)
        assert notes_text(env).count("Gedruckt") == 2
    finally:
        daemon.close()


def test_druck_nach_dienst_stopp_direkt_mit_hinweis(env, qtbot):
    from ipc_fakes import RestartableDaemon
    from tapesmith.ipc.backend import REASON_LOST, make_backend

    daemon = RestartableDaemon()
    local = FakeBackend()
    try:
        env.backend = make_backend({"daemon": {"spawn": False}}, P, client="tray",
                                   local_factory=lambda reason: local, env={}, connector=daemon.connector)
        app = env.make()
        old_client = app.backend.client
        daemon.stop()
        qtbot.waitUntil(lambda: old_client.closed, timeout=3000)
        app.print_test_label()
        wait_idle(qtbot, app)
        assert len(local.requests) == 1
        qtbot.waitUntil(lambda: REASON_LOST in notes_text(env))
        assert "Nicht gedruckt" not in notes_text(env)
    finally:
        daemon.close()
