"""Nach dem Abbau der Qt-Oberfläche bleiben die Module, die die Tray-App braucht.

`gui/tray.py` importiert `Relay` und `default_transport_factory` aus `gui/services.py` erst in
`default_backend_factory` (verzögert, Rückfall-Direktdruck ohne Dienst). Ein reiner Import von
`tapesmith.gui.tray` würde ein fehlendes `services.py` nicht bemerken; dieser Test durchläuft den
Rückfall-Zweig deshalb ausdrücklich. Es wird nie gedruckt."""

import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tapesmith import config as config_mod
from tapesmith.device.profile import load_profile
from tapesmith.gui import tray
from tapesmith.gui.services import Relay, default_transport_factory
from tapesmith.history import HistoryStore
from tapesmith.ipc.backend import LocalBackend

ROOT = Path(__file__).resolve().parents[1]

KEEP = ("tray", "hotkey", "qtutil", "theme", "icons", "preview_model", "recent", "services")
GONE = ("app", "main_window", "editor", "panels", "gallery_page", "templates_page",
        "template_form", "qr_page", "history_page", "settings_page", "queue_page", "inventory_page",
        "stats_page", "batch_dialog", "ssh_scan_dialog", "drive_assistant", "command_palette",
        "preview_widget", "fixbar", "print_controller", "status_widget", "status_detail", "tape_panel",
        "screencal",
        # Kein Fenster mehr: Schnelldruck-Popup, Zwischenablage-Toast,
        # Tray-Einstellungsdialog und die nur dafür gebaute Popup-Logik sind entfernt.
        "quick_popup", "clip_toast", "tray_settings", "quickgate")


def test_relay_und_transport_factory_vorhanden():
    got: list[int] = []
    relay = Relay()
    relay.connect(got.append)
    relay(1)
    assert got == [1]
    make = default_transport_factory({"transport": "memory"})
    assert callable(make)


@pytest.mark.parametrize("name", KEEP)
def test_behaltene_module_importierbar(name):
    importlib.import_module(f"tapesmith.gui.{name}")


@pytest.mark.parametrize("name", GONE)
def test_qt_oberflaeche_entfernt(name):
    base = ROOT / "src" / "tapesmith" / "gui"
    assert not (base / f"{name}.py").exists()
    assert not (base / name).exists()


def test_rueckfall_ohne_dienst_nutzt_services(tmp_path, monkeypatch):
    """Dienst aus: `default_backend_factory` baut den lokalen Rückfall mit dem verzögerten Import
    aus `gui/services.py` (Relay, default_transport_factory). Kein Druck."""
    monkeypatch.setenv("TAPESMITH_HOME", str(tmp_path / "home"))
    cfg = {**config_mod.DEFAULTS, "transport": "memory", "daemon": {"enabled": False},
           "idle_timeout_s": 0, "connect_timeout_s": 1, "guard": {}}
    history = HistoryStore(tmp_path / "h.db")
    backend = None
    try:
        backend = tray.default_backend_factory(history)(cfg, load_profile())
        assert isinstance(backend, LocalBackend)
    finally:
        if backend is not None:
            backend.close()
        history.close()


def test_tray_import_ohne_geloeschte_module():
    code = ("import sys, tapesmith.gui.tray, tapesmith.gui.services; "
            "bad = [m for m in sys.modules if m.startswith('tapesmith.gui.') and m.split('.')[2] in "
            f"{GONE!r}]; print(bad)")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env,
                            timeout=120, check=True)
    assert result.stdout.strip() == "[]", result.stderr
