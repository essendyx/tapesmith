"""Residente Tray-App: Symbol im Infobereich, Kontextmenü, globale Tastenkürzel.

Die Tray-App öffnet NIE ein eigenes Fenster, einen Dialog oder ein Popup. Nativ sind nur das
Tray-Symbol (`QSystemTrayIcon`) und sein Kontextmenü. Alles, was Oberfläche braucht, öffnet einen
neuen Tab im Standardbrowser (`webui.browser.open_app` mit Route, im Hintergrund):

* Linksklick auf das Symbol und „Web-Oberfläche öffnen“: Startseite der Web-Oberfläche
* „Schnelldruck“ und Tastenkürzel `hotkey.quick` (Strg+Alt+L): `/schnelldruck`
* „Zwischenablage in Schnelldruck“ und Tastenkürzel `hotkey.clipboard`: `/schnelldruck?text=...`
  mit dem Text der Zwischenablage (begrenzt, URL-kodiert, `browser.quick_route`), nie Direktdruck
* „Verlauf“: `/verlauf`, „Druckerstatus“: `/einstellungen?abschnitt=verbindung`,
  „Log und Diagnose“: `/einstellungen?abschnitt=support`,
  „Einstellungen“: `/einstellungen?abschnitt=tray`, Update-Hinweis: `/einstellungen?abschnitt=updates`
* Favorit mit fehlenden Eingaben: `/aktion?uri=tapesmith://print?...`

Direkt ohne Oberfläche wirken: Favoriten drucken, letzte Labels nachdrucken, Testlabel,
Warteschlange pausieren/fortsetzen, Autostart, Beenden. Hinweise und Fehler kommen als
Windows-Benachrichtigung des Tray-Symbols (`showMessage`), nie als Fenster.

Alle Einstellungen (Kürzel, an/aus, Favoriten, Benachrichtigungen, Autostart) stehen in der
Web-Oberfläche unter Einstellungen. Die Tray-App prüft die Konfigurationsdatei alle
`CONFIG_CHECK_MS` und übernimmt Änderungen ohne Neustart (`apply_settings`).

Tastenkürzel werden ohne Fenster registriert (`RegisterHotKey` mit hwnd NULL, Thread-Nachricht,
siehe `gui.hotkey`). Jeder Druck läuft mit Quelle "hotkey" über das Druck-Backend (Dienst oder
direkt). HiDPI-Symbole mit Statusabzeichen (`gui.icons`), Dunkelmodus des Menüs
nach `app.theme`, alle Texte über `tapesmith.i18n` (Sprache aus `app.language`).

Start: `python -m tapesmith.gui.tray`, `Tapesmith.exe --tray` oder `p12 tray`; eine Instanz je
Benutzer und App-Verzeichnis (ein eigenes `TAPESMITH_HOME` gibt also eine eigene Instanz).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from collections.abc import Callable, Sequence
from datetime import datetime
from urllib.parse import urlencode

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QAction, QGuiApplication, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from tapesmith import config, i18n, integration, modules, numbering, paths
from tapesmith.device.profile import DeviceProfile, load_profile
from tapesmith.document.render import render_spec
from tapesmith.errors import explain
from tapesmith.gui.hotkey import HotkeyManager, format_hotkey
from tapesmith.gui.qtutil import BackgroundCall
from tapesmith.history import HistoryEntry, HistoryStore, is_reprintable
from tapesmith.integration import RegistryBackend
from tapesmith.ipc.backend import PrintBackend, make_backend
from tapesmith.ipc.codec import StateInfo, StatusReport
from tapesmith.jobs import JobMeta
from tapesmith.labelmeta import text_meta
from tapesmith.pipeline import PrintLabel, PrintOutcome, PrintRequest, labels_from_result
from tapesmith.render.compose import LabelSpec
from tapesmith.render.fonts import FontMissing
from tapesmith.reprint import MissingSecrets, prepare_reprint
from tapesmith.statusview import status_view
from tapesmith.tape.profiles import TapeProfile, current_tape
from tapesmith.templates.fill import CounterStore, resolve_values
from tapesmith.templates.model import TemplateError
from tapesmith.templates.render import render_meta, render_template
from tapesmith.templates.store import find_template
from tapesmith.webui import browser

TRAY_SOURCE = "hotkey"
RECENT_COUNT = 5
RECENT_TITLE_MAX = 48
TOOLTIP_REFRESH_MS = 30_000
THEME_CHECK_MS = 30_000
CONFIG_CHECK_MS = 2_000
COMMIT_STATUSES = ("ok", "wartet")
QUICK_ROUTE = browser.QUICK_ROUTE
HISTORY_ROUTE = "/verlauf"
STATUS_ROUTE = "/einstellungen?abschnitt=verbindung"
LOG_ROUTE = "/einstellungen?abschnitt=support"
SETTINGS_ROUTE = "/einstellungen?abschnitt=tray"
UPDATE_ROUTE = "/einstellungen?abschnitt=updates"
_HOTKEY_KEYS = ("hotkey.enabled", "hotkey.quick", "hotkey.clipboard")


def tray_mutex_name() -> str:
    from tapesmith.ipc.pipe import home_key

    return f"Local\\Tapesmith.Tray.{home_key()}"


def make_icon(role: str, *, dark_taskbar: bool | None = None) -> QIcon:
    """HiDPI-Symbol mit Statusabzeichen (dünner Aufruf auf `gui.icons.make_status_icon`,
    bestehende Tests rufen weiter `make_icon(role)`)."""
    from tapesmith.gui.icons import make_status_icon

    return make_status_icon(role, dark_taskbar=dark_taskbar)


def default_clipboard_reader() -> str | None:
    """Text der Zwischenablage (Bilder werden nicht übernommen)."""
    return QGuiApplication.clipboard().text() or None


def config_stamp() -> tuple[int, int] | None:
    """Änderungsmarke der Konfigurationsdatei (mtime in ns, Größe); fehlt sie: None."""
    try:
        stat = paths.config_path().stat()
    except OSError:
        return None
    return (stat.st_mtime_ns, stat.st_size)


def default_backend_factory(history: HistoryStore) -> Callable[[dict, DeviceProfile], PrintBackend]:
    """Druckdienst oder, als Rückfall, Direktdruck über eine eigene Pipeline mit
    Verbindungsmanager (Verlauf, Fehldruckschutz, Rollen-/Band-Hooks, Archiv)."""

    def factory(cfg: dict, profile: DeviceProfile) -> PrintBackend:
        from tapesmith.archive import archive_hook
        from tapesmith.connection import ConnectionManager
        from tapesmith.guard import load_policy
        from tapesmith.gui.services import Relay, default_transport_factory
        from tapesmith.ipc.backend import LocalBackend, local_planner
        from tapesmith.pipeline import PrintPipeline, manager_runner
        from tapesmith.printhooks import print_hooks
        from tapesmith.tape.rolls import RollStore

        def local(reason: str) -> PrintBackend:
            state_relay, warning_relay, cut_relay = Relay(), Relay(), Relay()
            manager = ConnectionManager(default_transport_factory(cfg), profile,
                                        idle_timeout_s=float(cfg.get("idle_timeout_s", 300)),
                                        connect_timeout_s=float(cfg.get("connect_timeout_s", 5)),
                                        on_state=state_relay)
            tape_id = lambda: current_tape(cfg).id  # noqa: E731
            pipeline = PrintPipeline(profile, manager_runner(manager), history=history,
                                     policy=load_policy(cfg), preflight=True, on_warning=warning_relay,
                                     on_cut_pause=cut_relay, cut_pause_s=cfg.get("cut_pause_s"),
                                     **print_hooks(RollStore(tape=tape_id), tape_id))
            hook = archive_hook(cfg)
            return LocalBackend(pipeline, warning_relay=warning_relay, cut_pause_relay=cut_relay,
                                state_relay=state_relay, manager=manager,
                                post_hooks=[hook] if hook is not None else [], fallback_reason=reason)

        return make_backend(cfg, profile, client="tray", local_factory=local,
                            planner=local_planner(cfg, profile))

    return factory


class TrayApp(QObject):
    statusUpdated = Signal(str)        # Tooltip-Text (für Tests)
    _backendEvent = Signal(str, object)

    def __init__(self, *, config_loader: Callable[[], dict] = config.load_config,
                 profile_loader: Callable[[], DeviceProfile] | None = None,
                 backend_factory: Callable[[dict, DeviceProfile], PrintBackend] | None = None,
                 history_factory: Callable[[], HistoryStore] = HistoryStore,
                 hotkeys: HotkeyManager | None = None,
                 tray_icon_factory: Callable[[QObject], QSystemTrayIcon] | None = None,
                 clipboard_reader: Callable[[], str | None] | None = None,
                 browser_opener: Callable[[str | None], object] | None = None,
                 config_stamp_reader: Callable[[], object] | None = None,
                 registry_factory: Callable[[], RegistryBackend] = integration.WinRegBackend,
                 notify: Callable[[str, str], None] | None = None,
                 now: Callable[[], datetime] = datetime.now,
                 use_hotkeys: bool = True,
                 theme_reader: Callable[[], int] | None = None,
                 quit_app: Callable[[], None] | None = None) -> None:
        super().__init__()
        self._config_loader = config_loader
        self._profile_loader = profile_loader or (lambda: load_profile(calibration_path=paths.calibration_path()))
        self._backend_factory = backend_factory
        self._history_factory = history_factory
        self._hotkeys_given = hotkeys
        self._tray_icon_factory = tray_icon_factory or (lambda parent: QSystemTrayIcon(parent))
        self._clipboard_reader = clipboard_reader or default_clipboard_reader
        self._browser_opener = browser_opener or (
            lambda route: browser.open_app(route, config_loader=self._config_loader))
        self._config_stamp = config_stamp_reader or config_stamp
        self._registry_factory = registry_factory
        self._notify_fn = notify
        self._now = now
        self._use_hotkeys = use_hotkeys
        self._theme_reader = theme_reader
        self._quit_app = quit_app

        self._cfg: dict = {}
        self._profile: DeviceProfile | None = None
        self._history: HistoryStore | None = None
        self.backend: PrintBackend | None = None
        self.hotkeys: HotkeyManager | None = None
        self.tray_icon: QSystemTrayIcon | None = None
        self._menu: QMenu | None = None
        self._filter_installed = False
        self._listeners: list[tuple[str, Callable]] = []
        self._calls: set[BackgroundCall] = set()
        self._busy = False
        self._state = StateInfo("getrennt")
        self._report: StatusReport | None = None
        self._progress: tuple[int, int] | None = None
        self._queue_paused = False
        self._started = False
        self._connecting = False
        self._backend_call: BackgroundCall | None = None
        self._backend_stop_flag: threading.Event | None = None
        self._tooltip_timer: QTimer | None = None
        self._theme_timer: QTimer | None = None
        self._config_timer: QTimer | None = None
        self._last_stamp: object = None
        self._hotkey_state: tuple | None = None
        self._dark = False
        self._backendEvent.connect(self._on_backend_event)

    # ---------- Lebenszyklus ----------

    def start(self) -> None:
        """Symbol und Menü erscheinen sofort (Tooltip „verbinde mit Druckdienst …“); das
        Druck-Backend entsteht danach über `BackgroundCall` im Hintergrund (`_connect_backend`),
        damit ein langsamer oder fehlender Druckdienst den Start nicht blockiert."""
        self._last_stamp = self._read_stamp()
        self._cfg = self._config_loader()
        self._profile = self._profile_loader()
        self._history = self._history_factory()
        self._dark = self._effective_dark()

        self.tray_icon = self._tray_icon_factory(self)
        self.tray_icon.activated.connect(self._on_activated)
        self._build_menu()
        self.tray_icon.setContextMenu(self._menu)

        self._connecting = True
        self._setup_hotkeys()
        self.update_status()
        self.tray_icon.show()
        self._tooltip_timer = QTimer(self)
        self._tooltip_timer.setInterval(TOOLTIP_REFRESH_MS)
        self._tooltip_timer.timeout.connect(self.update_status)
        self._tooltip_timer.start()
        self._theme_timer = QTimer(self)
        self._theme_timer.setInterval(THEME_CHECK_MS)
        self._theme_timer.timeout.connect(self._check_theme)
        self._theme_timer.start()
        self._config_timer = QTimer(self)
        self._config_timer.setInterval(CONFIG_CHECK_MS)
        self._config_timer.timeout.connect(self.check_config)
        self._config_timer.start()
        self._started = True
        self._connect_backend()

    def _connect_backend(self) -> None:
        factory = self._backend_factory or default_backend_factory(self._history)
        cfg, profile = self._cfg, self._profile
        stop_flag = threading.Event()
        self._backend_stop_flag = stop_flag

        def build() -> PrintBackend:
            backend = factory(cfg, profile)
            if stop_flag.is_set():
                try:
                    backend.close()
                except Exception:  # noqa: BLE001: Tray beendet sich bereits
                    pass
            return backend

        call = BackgroundCall(build, self)
        self._backend_call = call
        call.finished.connect(self._on_backend_ready)
        call.failed.connect(self._on_backend_failed)
        call.start()

    def _on_backend_ready(self, backend: PrintBackend) -> None:
        self._backend_call = None
        self._backend_stop_flag = None
        self._connecting = False
        self.backend = backend
        if backend.fallback_reason:
            self._notify(self._tr("notify.hint.title"), backend.fallback_reason)
        try:
            self._state = backend.state_info()
        except Exception:  # noqa: BLE001
            self._state = StateInfo("getrennt")
        for event in ("state", "status", "progress", "queue"):
            callback = self._listener(event)
            backend.add_listener(event, callback)
            self._listeners.append((event, callback))
        self._refresh_queue_state()
        self._refresh_menu()
        self.update_status()

    def _on_backend_failed(self, exc: BaseException) -> None:
        self._backend_call = None
        self._backend_stop_flag = None
        self._connecting = False
        self.backend = None
        self._notify(self._tr("notify.backendUnavailable.title"), str(exc))
        self.update_status()

    def stop(self) -> None:
        if not self._started:
            return
        self._started = False
        if self._tooltip_timer is not None:
            self._tooltip_timer.stop()
        if self._theme_timer is not None:
            self._theme_timer.stop()
        if self._config_timer is not None:
            self._config_timer.stop()
        if self.hotkeys is not None:
            self.hotkeys.unregister_all()
            if self._filter_installed:
                app = QApplication.instance()
                if app is not None:
                    app.removeNativeEventFilter(self.hotkeys.native_filter())
                self._filter_installed = False
        if self._backend_call is not None:
            if self._backend_stop_flag is not None:
                self._backend_stop_flag.set()
            self._backend_call.abandon()
            self._backend_call = None
        for call in list(self._calls):
            call.abandon()
        self._calls.clear()
        if self.backend is not None:
            for event, callback in self._listeners:
                try:
                    self.backend.remove_listener(event, callback)
                except Exception:  # noqa: BLE001
                    pass
            self._listeners.clear()
            try:
                self.backend.close()
            except Exception:  # noqa: BLE001
                pass
        if self.tray_icon is not None:
            self.tray_icon.hide()
        if self._menu is not None:
            self._menu.deleteLater()
        if self._history is not None:
            self._history.close()

    def busy(self) -> bool:
        return self._busy

    def backend_pending(self) -> bool:
        """True, solange der asynchrone Aufbau des Druck-Backends noch läuft (Tests)."""
        return self._connecting

    # ---------- Sprache und Dunkelmodus ----------

    def _lang(self) -> str:
        return i18n.current_language(self._cfg)

    def _tr(self, key: str, **params) -> str:
        return i18n.tr(f"tray.{key}", self._lang(), **params)

    def _effective_dark(self) -> bool:
        from tapesmith.gui.theme import effective_dark

        return effective_dark(self._cfg, self._theme_reader)

    def _check_theme(self) -> None:
        """Alle `THEME_CHECK_MS` und bei jedem Öffnen des Menüs: bei geändertem Dunkelmodus
        (`app.theme` bzw. Windows-Registry) Palette und Symbol neu setzen."""
        dark = self._effective_dark()
        if dark == self._dark:
            return
        self._dark = dark
        from tapesmith.gui.theme import apply_theme

        app = QApplication.instance()
        if app is not None:
            apply_theme(app, dark)
        self.update_status()

    # ---------- Hotkeys ----------

    def _setup_hotkeys(self) -> None:
        if self.hotkeys is None:
            if self._hotkeys_given is not None:
                self.hotkeys = self._hotkeys_given
            else:
                # Kein Fenster: hwnd 0 heißt RegisterHotKey(NULL, ...), WM_HOTKEY kommt als
                # Thread-Nachricht in die Qt-Nachrichtenschleife (native_filter).
                self.hotkeys = HotkeyManager(parent=self)
            self.hotkeys.triggered.connect(self._on_hotkey)
        self._hotkey_state = self._current_hotkey_state()
        self.hotkeys.unregister_all()
        if not (self._use_hotkeys and config.setting(self._cfg, "hotkey.enabled")):
            return
        if not self._filter_installed:
            app = QApplication.instance()
            if app is not None:
                app.installNativeEventFilter(self.hotkeys.native_filter())
                self._filter_installed = True
        for name in ("quick", "clipboard"):
            error = self.hotkeys.register(name, str(config.setting(self._cfg, f"hotkey.{name}")))
            if error is not None:
                self._notify(self._tr("notify.hotkeyInactive.title"), error)

    def _current_hotkey_state(self) -> tuple:
        return (self._use_hotkeys,) + tuple(config.setting(self._cfg, key) for key in _HOTKEY_KEYS)

    def _on_hotkey(self, name: str) -> None:
        if name == "quick":
            self.open_quick()
        elif name == "clipboard":
            self.open_clipboard()

    def _hotkey_label(self, name: str) -> str:
        """Kürzel hinter dem Menütext, nur wenn es wirklich registriert ist."""
        if not (self._use_hotkeys and config.setting(self._cfg, "hotkey.enabled")):
            return ""
        spec = self.hotkeys.registered().get(name) if self.hotkeys is not None else None
        if spec is None:
            return ""
        return self._tr("menu.hotkeySuffix", hotkey=format_hotkey(spec))

    # ---------- Menü ----------

    def _action(self, menu: QMenu, name: str, text: str, slot: Callable[[], None] | None = None, *,
                checkable: bool = False) -> QAction:
        action = QAction(text, menu)
        action.setObjectName(name)
        action.setCheckable(checkable)
        if slot is not None:
            action.triggered.connect(lambda _checked=False: slot())
        menu.addAction(action)
        return action

    def _build_menu(self) -> None:
        """Nur Einträge, die direkt etwas tun oder einen Browser-Tab öffnen (kein Fenster)."""
        menu = QMenu()
        menu.setObjectName("trayMenu")
        self._menu = menu
        self._action(menu, "trayUpdate", self._tr("menu.updateCheck"), self.open_update_route)
        menu.addSeparator()
        main_action = self._action(menu, "trayMain", self._tr("menu.main"), self.open_app_window)
        main_font = main_action.font()
        main_font.setBold(True)
        main_action.setFont(main_font)
        menu.setDefaultAction(main_action)
        self._action(menu, "trayQuick", self._tr("menu.quick"), self.open_quick)
        self._action(menu, "trayClipboard", self._tr("menu.clipboard"), self.open_clipboard)
        self._favorites_menu = menu.addMenu(self._tr("menu.favorites"))
        self._favorites_menu.setObjectName("trayFavorites")
        self._favorites_menu.menuAction().setObjectName("trayFavorites")
        self._recent_menu = menu.addMenu(self._tr("menu.recent"))
        self._recent_menu.setObjectName("trayRecent")
        self._recent_menu.menuAction().setObjectName("trayRecent")
        self._action(menu, "trayTest", self._tr("menu.test"), self.print_test_label)
        menu.addSeparator()
        self._action(menu, "trayHistory", self._tr("menu.history"), self.open_history)
        self._action(menu, "trayQueuePause", self._tr("menu.queuePause"), self.toggle_queue_pause,
                     checkable=True)
        self._action(menu, "trayStatus", self._tr("menu.status"), self.open_status)
        self._action(menu, "trayLog", self._tr("menu.log"), self.open_log)
        menu.addSeparator()
        self._action(menu, "traySettings", self._tr("menu.settings"), self.open_settings)
        autostart = self._action(menu, "trayAutostart", self._tr("menu.autostart"), checkable=True)
        autostart.triggered.connect(lambda checked: self.set_autostart(bool(checked)))
        menu.addSeparator()
        self._action(menu, "trayQuit", self._tr("menu.quit"), self._quit)
        menu.aboutToShow.connect(self._on_menu_show)
        self._refresh_menu()

    def _refresh_menu(self) -> None:
        actions = self._collect_actions()
        actions["trayUpdate"].setText(self._update_menu_text())
        actions["trayMain"].setText(self._tr("menu.main"))
        actions["trayQuick"].setText(self._tr("menu.quick") + self._hotkey_label("quick"))
        actions["trayClipboard"].setText(self._tr("menu.clipboard") + self._hotkey_label("clipboard"))
        self._favorites_menu.menuAction().setText(self._tr("menu.favorites"))
        self._recent_menu.menuAction().setText(self._tr("menu.recent"))
        actions["trayTest"].setText(self._tr("menu.test"))
        actions["trayHistory"].setText(self._tr("menu.history"))
        pause = actions["trayQueuePause"]
        pause.setText(self._tr("menu.queuePause"))
        pause.setEnabled(self._queue_ops() is not None)
        pause.setChecked(self._queue_paused)
        actions["trayStatus"].setText(self._tr("menu.status"))
        actions["trayLog"].setText(self._tr("menu.log"))
        actions["traySettings"].setText(self._tr("menu.settings"))
        actions["trayAutostart"].setText(self._tr("menu.autostart"))
        actions["trayQuit"].setText(self._tr("menu.quit"))
        try:
            actions["trayAutostart"].setChecked(self.autostart_enabled())
        except Exception:  # noqa: BLE001 (Registry nicht lesbar: Häkchen weglassen)
            actions["trayAutostart"].setChecked(False)
        self._rebuild_favorites_menu()
        self.rebuild_recent_menu()

    def _on_menu_show(self) -> None:
        self.check_config()
        self._cfg = self._config_loader()
        self._check_theme()
        self._refresh_menu()

    def _rebuild_favorites_menu(self) -> None:
        menu = self._favorites_menu
        menu.clear()
        favorites = self._favorites()
        if not favorites:
            action = self._action(menu, "trayFavoritesEmpty", self._tr("menu.favoritesEmpty"))
            action.setEnabled(False)
        for index, fav in enumerate(favorites):
            title = str(fav.get("title") or fav.get("template") or self._tr("favorite.default", index=index + 1))
            self._action(menu, f"trayFavorite{index}", title, lambda i=index: self.print_favorite(i))

    def rebuild_recent_menu(self) -> None:
        menu = self._recent_menu
        menu.clear()
        try:
            entries = self.recent_entries()
        except Exception:  # noqa: BLE001 (Verlauf nicht lesbar: Menü leer lassen)
            entries = []
        if not entries:
            action = self._action(menu, "trayRecentEmpty", self._tr("menu.recentEmpty"))
            action.setEnabled(False)
        for entry in entries:
            title = entry.title if len(entry.title) <= RECENT_TITLE_MAX else entry.title[:RECENT_TITLE_MAX - 1] + "…"
            self._action(menu, f"trayRecent{entry.id}", f"#{entry.id} {title}",
                         lambda i=entry.id: self.reprint_recent(i))

    def _collect_actions(self) -> dict[str, QAction]:
        found: dict[str, QAction] = {}

        def walk(menu: QMenu) -> None:
            for action in menu.actions():
                if action.objectName():
                    found.setdefault(action.objectName(), action)
                if action.menu() is not None:
                    walk(action.menu())

        if self._menu is not None:
            walk(self._menu)
        return found

    def menu_actions(self) -> dict[str, QAction]:
        return self._collect_actions()

    def _favorites(self) -> list[dict]:
        """Favoriten aus `tray.favorites` ohne Vorlagen ausgeschalteter Module."""
        favorites = config.setting(self._cfg, "tray.favorites")
        if not isinstance(favorites, list):
            return []
        try:
            hidden = modules.hidden_templates(self._cfg)
        except Exception:  # noqa: BLE001 (Datenordner nicht lesbar: nichts ausblenden)
            hidden = frozenset()
        return [f for f in favorites if isinstance(f, dict) and f.get("template") not in hidden]

    # ---------- Update-Hinweis ----------

    def _read_update_state(self) -> dict | None:
        """`<App-Verzeichnis>\\update\\state.json`; fehlend oder kaputt -> None."""
        path = paths.app_dir() / "update" / "state.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def _available_update_version(self) -> str | None:
        state = self._read_update_state()
        if not isinstance(state, dict) or not state.get("installed"):
            return None
        available = state.get("available")
        if not isinstance(available, dict):
            return None
        version = available.get("version")
        return str(version) if version else None

    def _update_menu_text(self) -> str:
        version = self._available_update_version()
        if version:
            return self._tr("menu.updateAvailable", version=version)
        return self._tr("menu.updateCheck")

    def open_update_route(self) -> None:
        self.open_web(UPDATE_ROUTE)

    # ---------- Aktionen ----------

    def _on_activated(self, reason) -> None:
        """Linksklick auf das Symbol: Web-Oberfläche im Browser (kein Fenster)."""
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.open_app_window()

    def open_quick(self) -> None:
        """Schnelldruck (Tastenkürzel Strg+Alt+L, Menü): `/schnelldruck` im Browser."""
        self.open_web(QUICK_ROUTE)

    def open_clipboard(self) -> None:
        """Zwischenablage-Kürzel bzw. Menü: `/schnelldruck` mit dem Text der Zwischenablage
        vorbelegt. Gedruckt wird erst in der Web-Oberfläche, nie direkt."""
        try:
            text = self._clipboard_reader()
        except Exception as exc:  # noqa: BLE001
            self._notify(self._tr("notify.clipboardUnreadable.title"), str(exc))
            return
        route, truncated = browser.quick_route(text)
        if route == QUICK_ROUTE:
            self._notify(self._tr("notify.clipboardEmpty.title"), self._tr("notify.clipboardEmpty.text"))
            return
        if truncated:
            self._notify(self._tr("notify.clipboardTruncated.title"),
                        self._tr("notify.clipboardTruncated.text", max=browser.CLIP_TEXT_MAX))
        self.open_web(route)

    @staticmethod
    def _commit(counters: CounterStore, keys: Sequence[str]) -> None:
        for key in keys:
            counters.commit(key)

    def print_favorite(self, index: int) -> None:
        favorites = self._favorites()
        if not 0 <= index < len(favorites):
            return
        fav = favorites[index]
        values = {str(k): str(v) for k, v in (fav.get("values") or {}).items()}
        try:
            template = find_template(str(fav.get("template", "")))
        except TemplateError as exc:
            self._notify(self._tr("notify.favoriteNotPrintable.title"), str(exc))
            return
        counters = self.counters()
        try:
            resolved = resolve_values(template, values, self._now(), counters)
            tr = render_template(template, resolved.values, self._profile, tape=self._tape())
        except TemplateError as exc:
            self._notify(self._tr("notify.inputsMissing.title"), self._tr("notify.inputsMissing.text", error=exc))
            uri = "tapesmith://print?" + urlencode({"template": template.name, **values})
            self.open_web(browser.build_route(uri=uri))
            return
        except (ValueError, FontMissing) as exc:
            self._notify(self._tr("notify.favoriteNotPrintable.title"), str(exc))
            return
        if tr.tape_reason:
            self._notify(self._tr("notify.notPrinted.title"),
                        self._tr("notify.notPrinted.tapeReason", reason=tr.tape_reason))
            return
        keys = resolved.counter_keys
        self.submit(labels_from_result(tr.result), render_meta(tr, source=TRAY_SOURCE),
                    on_done=lambda _outcome: self._commit(counters, keys))

    def reprint_recent(self, entry_id: int) -> None:
        if self._history is None:
            return
        try:
            entry = self._history.get(entry_id)
            job = prepare_reprint(self._history, entry, self._profile, source=TRAY_SOURCE, now=self._now,
                                  counters=self.counters(), tape=self._tape())
        except MissingSecrets as exc:
            self._notify(self._tr("notify.reprintOnlyMain.title"), str(exc))
            return
        except (KeyError, ValueError, TemplateError, FontMissing) as exc:
            self._notify(self._tr("notify.reprintNotPossible.title"), str(exc))
            return
        self.submit(job.labels, job.meta, copies=job.copies, chain=job.chain,
                    on_done=lambda _outcome: job.commit_counters())

    def print_test_label(self) -> None:
        spec = LabelSpec(lines=("Tapesmith", f"Test {self._now():%d.%m.%Y %H:%M}"))
        try:
            result = render_spec(spec, self._profile, self._tape())
        except (ValueError, FontMissing) as exc:
            self._notify(self._tr("notify.testNotPrintable.title"), str(exc))
            return
        meta = text_meta(spec, source=TRAY_SOURCE)
        meta = JobMeta(source=meta.source, kind="test", title=meta.title, spec=meta.spec)
        self.submit(labels_from_result(result), meta)

    def _queue_ops(self):
        if self.backend is None:
            return None
        try:
            return self.backend.queue_ops()
        except Exception:  # noqa: BLE001
            return None

    def toggle_queue_pause(self) -> None:
        action = self._collect_actions().get("trayQueuePause")
        ops = self._queue_ops()
        if ops is None:
            if action is not None:
                action.setChecked(False)
                action.setEnabled(False)
            return
        want_paused = not self._queue_paused
        try:
            ops.pause() if want_paused else ops.resume()
        except Exception as exc:  # noqa: BLE001
            self._notify(self._tr("notify.queue.title"), str(exc))
        else:
            self._queue_paused = want_paused
        if action is not None:
            action.setChecked(self._queue_paused)

    def _refresh_queue_state(self) -> None:
        ops = self._queue_ops()
        if ops is None:
            return
        self._run(ops.list, self._on_queue_list, lambda _exc: None)

    def _on_queue_list(self, snapshot) -> None:
        self._queue_paused = bool(getattr(snapshot, "paused", False))
        action = self._collect_actions().get("trayQueuePause")
        if action is not None:
            action.setChecked(self._queue_paused)

    def query_status(self) -> None:
        backend = self.backend
        if backend is None:
            if self._connecting:
                self._notify(self._tr("notify.statusUnavailable.title"), self._tr("notify.connecting"))
            return
        self._run(lambda: backend.query_status(fresh=True), self._on_report,
                  lambda exc: self._notify(self._tr("notify.statusUnavailable.title"), self._error_text(exc)))

    def _on_report(self, report: StatusReport) -> None:
        self._report = report
        self._state = report.state
        self.update_status()

    def open_app_window(self) -> None:
        """„Web-Oberfläche öffnen“ und Linksklick: die Web-Oberfläche im Standardbrowser
        (Startseite). Jedes Öffnen ist ein neuer Tab mit frischem Sitzungstoken; alle Tabs zeigen
        denselben Stand, weil der Druckdienst die Daten hält."""
        self.open_web()

    def open_history(self) -> None:
        self.open_web(HISTORY_ROUTE)

    def open_status(self) -> None:
        """„Druckerstatus“: Verbindungsabschnitt der Einstellungen (Status und Verbinden)."""
        self.open_web(STATUS_ROUTE)

    def open_web(self, route: str | None = None) -> None:
        """Web-Oberfläche auf `route` im Standardbrowser öffnen. Dienststart und Browseraufruf
        laufen im Hintergrund (das Tray friert nie ein); scheitert eines davon, erscheint eine
        Benachrichtigung mit dem Grund."""
        opener = self._browser_opener
        self._run(lambda: opener(route), lambda _url: None,
                  lambda exc: self._notify(self._tr("notify.openFailed.title"), str(exc)))

    def open_log(self) -> None:
        """„Log und Diagnose“: Abschnitt Hilfe und Diagnose der Einstellungen im Browser."""
        self.open_web(LOG_ROUTE)

    def open_settings(self) -> None:
        """„Einstellungen“: Abschnitt Tray und Tastenkürzel der Web-Oberfläche im Browser."""
        self.open_web(SETTINGS_ROUTE)

    def _read_stamp(self) -> object:
        try:
            return self._config_stamp()
        except Exception:  # noqa: BLE001 (nicht lesbar: wie fehlend)
            return None

    def check_config(self) -> bool:
        """Alle `CONFIG_CHECK_MS`: hat sich die Konfigurationsdatei geändert (Web-Einstellungen,
        `p12 config`), gelten die neuen Werte sofort (`apply_settings`). True bei Änderung."""
        stamp = self._read_stamp()
        if stamp == self._last_stamp:
            return False
        self._last_stamp = stamp
        try:
            self.apply_settings()
        except Exception as exc:  # noqa: BLE001 (kaputte Datei: alter Stand bleibt aktiv)
            self._notify(self._tr("notify.configInvalid.title"), str(exc))
        return True

    def apply_settings(self) -> None:
        """Config neu laden; Tastenkürzel nur bei geänderten `hotkey.*` neu registrieren, dazu
        Menütexte, Sprache und Dunkelmodus (alles ohne Neustart)."""
        self._cfg = self._config_loader()
        if self.hotkeys is None or self._current_hotkey_state() != self._hotkey_state:
            self._setup_hotkeys()
        self._check_theme()
        if self._menu is not None:
            self._refresh_menu()

    def set_autostart(self, on: bool) -> None:
        try:
            registry = self._registry_factory()
            if on:
                integration.install(registry, parts=("autostart",))
            else:
                integration.uninstall(registry, parts=("autostart",))
        except (OSError, RuntimeError) as exc:
            self._notify(self._tr("notify.autostartFailed.title"), str(exc))
        action = self._collect_actions().get("trayAutostart")
        if action is not None:
            try:
                action.setChecked(self.autostart_enabled())
            except Exception:  # noqa: BLE001
                action.setChecked(False)

    def autostart_enabled(self) -> bool:
        return integration.status(self._registry_factory()).get("autostart") == "installiert"

    def _quit(self) -> None:
        self.stop()
        if self._quit_app is not None:
            self._quit_app()
        else:
            app = QApplication.instance()
            if app is not None:
                app.quit()

    # ---------- Druck ----------

    def counters(self) -> CounterStore:
        """Immer der zentrale Zählerspeicher aus `numbering.dir`."""
        return numbering.counter_store(self._cfg)

    def submit(self, labels: tuple[PrintLabel, ...], meta: JobMeta, *, copies: int = 1, chain: bool = False,
               on_done: Callable[[PrintOutcome], None] | None = None) -> None:
        backend = self.backend
        if backend is None:
            if self._connecting:
                self._notify(self._tr("notify.notPrinted.title"), self._tr("notify.connecting"))
            else:
                self._notify(self._tr("notify.notPrinted.title"), self._tr("notify.notPrinted.noBackend"))
            return
        if self._busy:
            self._notify(self._tr("notify.notPrinted.title"), self._tr("notify.notPrinted.busy"))
            return
        request = PrintRequest(tuple(labels), meta, copies=copies, chain=chain)
        enqueue = bool(config.setting(self._cfg, "queue.enabled"))
        self._busy = True
        self._run(lambda: backend.execute(request, enqueue_on_offline=enqueue),
                  lambda outcome: self._on_outcome(outcome, meta, on_done),
                  self._on_print_failed)

    def _on_outcome(self, outcome: PrintOutcome, meta: JobMeta,
                    on_done: Callable[[PrintOutcome], None] | None) -> None:
        self._busy = False
        self._progress = None
        self.update_status()
        status = outcome.status
        if status in COMMIT_STATUSES and on_done is not None:
            try:
                on_done(outcome)
            except Exception as exc:  # noqa: BLE001
                self._notify(self._tr("notify.countersFailed.title"), str(exc))
        if status == "ok":
            hints = list(dict.fromkeys(outcome.warnings))
            text = self._tr("notify.printed.withHints", title=meta.title, hints="; ".join(hints)) if hints \
                else meta.title
            self._notify(self._tr("notify.printed.title"), text, success=True)
        elif status == "wartet":
            self._notify(self._tr("notify.waiting.title", queueId=outcome.queue_id), self._tr("notify.waiting.text"))
        elif status == "bestätigung_nötig":
            self._notify(self._tr("notify.confirmNeeded.title"),
                        self._tr("notify.confirmNeeded.text", reasons="; ".join(outcome.reasons)))
        elif status == "abgebrochen":
            self._notify(self._tr("notify.cancelled.title"), self._tr("notify.cancelled.text"))
        elif status == "unvollständig":
            text = self._error_text(outcome.error) if outcome.error is not None \
                else self._tr("notify.incomplete.fallbackText")
            self._notify(self._tr("notify.incomplete.title"), text)
        else:
            self._notify(self._tr("notify.notPrinted.title"), "; ".join(outcome.reasons) or status)

    def _on_print_failed(self, exc: BaseException) -> None:
        self._busy = False
        self._progress = None
        self.update_status()
        self._notify(self._tr("notify.notPrinted.title"), self._error_text(exc))

    def _error_text(self, exc: BaseException) -> str:
        """Titel über den Fehlercode aus dem Katalog, Hinweis bei `en` ebenfalls aus dem
        Katalog, bei `de` wie bisher (`errors.explain`)."""
        lang = self._lang()
        advice = explain(exc)
        title = i18n.tr(f"errors.{advice.code}.title", lang)
        hint = i18n.tr(f"errors.{advice.code}.hint", lang) if lang == "en" else advice.hint
        text = f"{title}: {exc}"
        return f"{text}. {hint}" if hint else text

    def _run(self, fn: Callable[[], object], on_ok: Callable[[object], None],
             on_error: Callable[[BaseException], None]) -> None:
        call = BackgroundCall(fn, self)
        self._calls.add(call)

        def finished(result: object) -> None:
            self._calls.discard(call)
            on_ok(result)

        def failed(exc: BaseException) -> None:
            self._calls.discard(call)
            on_error(exc)

        call.finished.connect(finished)
        call.failed.connect(failed)
        call.start()

    # ---------- Status ----------

    def _listener(self, event: str) -> Callable[[object], None]:
        return lambda data: self._backendEvent.emit(event, data)

    def _on_backend_event(self, event: str, data: object) -> None:
        if event == "state" and isinstance(data, StateInfo):
            self._state = data
        elif event == "status" and isinstance(data, StatusReport):
            self._report = data
            self._state = data.state
        elif event == "progress" and isinstance(data, dict):
            done, total = int(data.get("done", 0)), int(data.get("total", 0))
            self._progress = (done, total) if total > 0 and done < total else None
        elif event == "queue":
            self._refresh_queue_state()
            return
        self.update_status()

    def tooltip(self) -> str:
        if self._connecting and self.backend is None:
            return self._tr("notify.connectingTooltip")
        with i18n.use_language(self._lang()):
            view = status_view(self._state, self._report, now=self._now(), mac=self._cfg.get("mac"))
        if self._progress is not None:
            done, total = self._progress
            return self._tr("notify.printingTooltip", percent=int(done * 100 / total), status=view.tooltip)[:127]
        return view.tooltip

    def update_status(self) -> None:
        tip = self.tooltip()
        if self.tray_icon is not None:
            view = status_view(self._state, self._report, now=self._now())
            self.tray_icon.setIcon(make_icon(view.role, dark_taskbar=self._dark))
            self.tray_icon.setToolTip(tip)
        self.statusUpdated.emit(tip)

    def recent_entries(self, n: int = RECENT_COUNT) -> list[HistoryEntry]:
        if self._history is None:
            return []
        result = []
        for entry in self._history.search("", limit=max(50, n * 10)):
            if entry.status == "ok" and not entry.sensitive and is_reprintable(entry):
                result.append(entry)
                if len(result) >= n:
                    break
        return result

    # ---------- Hilfen ----------

    def _tape(self) -> TapeProfile | None:
        try:
            return current_tape(self._cfg)
        except (ValueError, OSError):
            return None

    def _notify(self, title: str, text: str, *, success: bool = False) -> None:
        if success and not config.setting(self._cfg, "tray.notify"):
            return
        if self._notify_fn is not None:
            self._notify_fn(title, text)
        elif self.tray_icon is not None:
            self.tray_icon.showMessage(title or i18n.tr("common.app.name", self._lang()), text,
                                       QSystemTrayIcon.MessageIcon.Information, 5000)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tapesmith-tray", description=i18n.tr("tray.cli.description"))
    parser.add_argument("--no-hotkeys", action="store_true", help=i18n.tr("tray.cli.noHotkeys"))
    args = parser.parse_args(argv)

    from tapesmith.daemon.instance import SingleInstance

    instance = SingleInstance(tray_mutex_name())
    if not instance.acquire():
        return 0
    tray: TrayApp | None = None
    try:
        app = QApplication.instance() or QApplication(sys.argv[:1])
        app.setQuitOnLastWindowClosed(False)
        from tapesmith.gui.theme import apply_theme

        apply_theme(app)
        tray = TrayApp(use_hotkeys=not args.no_hotkeys)
        tray.start()
        return int(app.exec())
    finally:
        if tray is not None:
            tray.stop()
        instance.release()


if __name__ == "__main__":
    sys.exit(main())
