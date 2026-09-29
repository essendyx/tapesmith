"""Module bei der Übernahme aus "P12 Label" und bei älteren Konfigurationen: wer Daten eines Moduls
hat, behält das Modul eingeschaltet (im Zweifel alle)."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from tapesmith import config, migrate, modules, paths

FIXED_NOW = lambda: datetime(2026, 9, 29, 12, 0, 0)  # noqa: E731


def _history(path, templates):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE jobs(id INTEGER PRIMARY KEY, template TEXT)")
    conn.executemany("INSERT INTO jobs(template) VALUES (?)", [(t,) for t in templates])
    conn.commit()
    conn.close()


def _inventory(path, boxes):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE boxes(id TEXT PRIMARY KEY)")
    conn.executemany("INSERT INTO boxes(id) VALUES (?)", [(b,) for b in boxes])
    conn.commit()
    conn.close()


def _legacy(appdata, *, config_data=None, homelab=None, history=(), boxes=()):
    old = appdata / "P12Label"
    old.mkdir(parents=True)
    (old / "config.json").write_text(json.dumps(config_data or {"transport": "auto"}), encoding="utf-8")
    if homelab is not None:
        (old / "homelab.json").write_text(json.dumps(homelab), encoding="utf-8")
    _history(old / "history.sqlite3", history)
    _inventory(old / "inventory.sqlite3", boxes)
    return old


def _enabled(folder):
    return json.loads((folder / "config.json").read_text(encoding="utf-8"))["modules"]["enabled"]


def test_uebernahme_schaltet_benutzte_module_ein(tmp_path):
    appdata = tmp_path / "appdata"
    old = _legacy(appdata, config_data={"transport": "auto", "ssh": {"hosts": [{"name": "nas", "host": "nas",
                                                                             "key": "k"}]}},
                  homelab={"proxmox": {"hosts": [{"name": "pve", "url": "https://192.0.2.5:8006",
                                                  "token_ref": "env:PVE"}]},
                           "obsidian": {"mcp_url": "http://192.0.2.12:8092/mcp"}},
                  history=["gefriergut", "asn", "ka-artikel"], boxes=["BOX-01"])
    new = appdata / "Tapesmith"
    assert migrate.migrate_legacy_data(old, new, now=FIXED_NOW) is True
    assert _enabled(new) == ["inventar", "datentraeger", "proxmox", "paperless", "vault", "kleinanzeigen",
                             "snscan"]
    data = json.loads((new / "config.json").read_text(encoding="utf-8"))
    assert data["transport"] == "auto"
    # Original bleibt unverändert
    assert "modules" not in json.loads((old / "config.json").read_text(encoding="utf-8"))
    log = (new / "logs" / "migration.log").read_text(encoding="utf-8")
    assert "Module eingeschaltet: inventar, datentraeger" in log


def test_uebernahme_ohne_moduldaten_schaltet_nichts_ein(tmp_path):
    appdata = tmp_path / "appdata"
    old = _legacy(appdata, history=["gefriergut", "geoeffnet-am"])
    new = appdata / "Tapesmith"
    assert migrate.migrate_legacy_data(old, new, now=FIXED_NOW) is True
    assert _enabled(new) == []
    assert "Module eingeschaltet: keine" in (new / "logs" / "migration.log").read_text(encoding="utf-8")


def test_uebernahme_im_zweifel_alle(tmp_path):
    appdata = tmp_path / "appdata"
    old = _legacy(appdata)
    (old / "homelab.json").write_text("{kaputt", encoding="utf-8")
    new = appdata / "Tapesmith"
    assert migrate.migrate_legacy_data(old, new, now=FIXED_NOW) is True
    assert _enabled(new) == list(modules.MODULE_IDS)


def test_uebernahme_ohne_config_legt_modulliste_an(tmp_path):
    appdata = tmp_path / "appdata"
    old = appdata / "P12Label"
    old.mkdir(parents=True)
    _inventory(old / "inventory.sqlite3", ["BOX-01"])
    new = appdata / "Tapesmith"
    assert migrate.migrate_legacy_data(old, new, now=FIXED_NOW) is True
    assert _enabled(new) == ["inventar"]


def test_vorhandene_modulliste_bleibt(tmp_path):
    appdata = tmp_path / "appdata"
    old = _legacy(appdata, config_data={"modules": {"enabled": ["kabel"]}}, boxes=["BOX-01"])
    new = appdata / "Tapesmith"
    assert migrate.migrate_legacy_data(old, new, now=FIXED_NOW) is True
    assert _enabled(new) == ["kabel"]


def test_druckdienst_schreibt_erkannte_liste_einmal_fest(real_module_detection):
    home = paths.app_dir()
    config.save_config({"transport": "auto"})
    _inventory(home / "inventory.sqlite3", ["BOX-01"])
    assert modules.persist_detected_if_missing() == ("inventar",)
    assert json.loads(paths.config_path().read_text(encoding="utf-8"))["modules"] == {"enabled": ["inventar"]}
    # zweiter Aufruf ändert nichts mehr
    modules.set_enabled("kabel", True)
    assert modules.persist_detected_if_missing() is None
    assert modules.enabled_ids(config.load_config()) == ("inventar", "kabel")


def test_ohne_config_json_nichts_festzuschreiben(real_module_detection):
    assert not paths.config_path().exists()
    assert modules.persist_detected_if_missing() is None
    assert not paths.config_path().exists()
