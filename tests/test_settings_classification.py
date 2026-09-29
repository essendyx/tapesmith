"""Einordnung jeder Einstellung: S = sichtbar, E = Abschnitt "Erweitert" (eingeklappt am Seitenende),
C = nur config.json (dokumentiert im Handbuch), X = entfällt. Dazu Einheiten und Hilfetexte aller
sichtbaren Zahlenfelder und die Rasterweite in mm."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tapesmith import config as config_mod
from tapesmith import paths
from tapesmith.webapi import settings_schema
from webapi_fakes import close_ctx, make_client

HANDBUCH = (Path(__file__).resolve().parent.parent / "docs" / "handbuch.md").read_text(encoding="utf-8")

S, E, C = "sichtbar", "erweitert", "config"

EINORDNUNG: dict[str, str] = {
    # Drucker (Status, Suchen und testen, Testlabel sind eigene Bausteine, sichtbar)
    "mac": E, "transport": E, "connect_timeout_s": C, "idle_timeout_s": C,
    # Drucken
    "gui.ctrl_enter_only": S, "cut_pause_s": S, "guard.confirm_label_mm": S, "guard.confirm_copies": S,
    "guard.max_label_mm": E, "guard.max_request_mm": E, "guard.max_copies": E,
    # Warteschlange
    "queue.enabled": S, "queue.auto_retry": S, "queue.probe": C, "queue.backoff_start_s": C,
    "queue.backoff_max_s": C, "queue.cli_default": C, "status.poll_s": C,
    # Editor
    "gui.editor_snap": S, "gui.editor_grid_mm": S, "gui.editor_grid_dots": C, "gui.screen_px_per_mm": C,
    # Tray und Tastenkürzel, Oberfläche
    "hotkey.enabled": S, "hotkey.quick": S, "hotkey.clipboard": S, "tray.notify": S, "tray.favorites": S,
    "app.language": S, "app.theme": S,
    # Updates
    "update.enabled": S, "update.auto_install": S, "update.channel": S, "update.source": C,
    "update.check_interval_h": C, "update.idle_min": C, "update.keep_versions": C,
    # Sicherung, Vorlagen, Archiv
    "backup.auto_daily": S, "backup.keep": S, "backup.dir": E, "templates_dir": E,
    "archive.dir": E, "archive.git_commit": E, "numbering.dir": C,
    # Druckdienst, Bluetooth LE
    "daemon.idle_exit_s": C, "web.port": E, "ble.address": E, "ble.scan_timeout_s": E,
}
ENTFAELLT = ("update.token_ref",)
MODUL_FELDER = {"ssh.hosts": "datentraeger", "ssh.timeout_s": "datentraeger", "ssh.strict_host_key": "datentraeger"}


@pytest.fixture
def api(tmp_path):
    client, ctx = make_client(tmp_path)
    yield client, ctx
    close_ctx(ctx)


def _schema_fields() -> dict:
    return {spec.key: (section, spec) for section in settings_schema.SECTIONS for spec in section.fields}


def test_einordnung_vollstaendig_und_fest():
    fields = _schema_fields()
    assert set(fields) == set(EINORDNUNG) | set(MODUL_FELDER)
    for key, expected in EINORDNUNG.items():
        section, spec = fields[key]
        assert section.module is None, key
        assert spec.visibility == expected, key
    for key, module_id in MODUL_FELDER.items():
        section, spec = fields[key]
        assert section.module == module_id, key
        assert spec.visibility == S, key
    for key in ENTFAELLT:
        assert key not in fields


def test_get_settings_liefert_nur_sichtbare_und_erweiterte(api):
    client, _ctx = api
    body = client.get("/api/v1/settings").json()
    served = {f["key"]: f["visibility"] for s in body["sections"] for f in s["fields"]}
    for key, expected in EINORDNUNG.items():
        if expected == C:
            assert key not in served, key
        else:
            assert served[key] == expected, key
    for key in ENTFAELLT:
        assert key not in served


def test_modulabschnitt_nur_mit_eingeschaltetem_modul(api):
    client, _ctx = api
    body = client.get("/api/v1/settings").json()
    ssh = next(s for s in body["sections"] if s["id"] == "ssh")
    assert ssh["module"] == "datentraeger"
    client.put("/api/v1/modules/datentraeger", json={"enabled": False})
    ids = [s["id"] for s in client.get("/api/v1/settings").json()["sections"]]
    assert "ssh" not in ids


def test_config_felder_bleiben_ueber_patch_setzbar(api):
    client, _ctx = api
    r = client.patch("/api/v1/settings", json={"changes": {"gui.screen_px_per_mm": 4.0, "queue.probe": "off"}})
    assert r.status_code == 200, r.text
    cfg = config_mod.load_config()
    assert config_mod.setting(cfg, "gui.screen_px_per_mm") == 4.0
    assert config_mod.setting(cfg, "queue.probe") == "off"


def test_token_ref_ist_kein_einstellungsschluessel_mehr(api):
    client, _ctx = api
    before = paths.config_path().read_text(encoding="utf-8")
    r = client.patch("/api/v1/settings", json={"changes": {"update.token_ref": None}})
    assert r.status_code == 422
    assert paths.config_path().read_text(encoding="utf-8") == before


@pytest.mark.parametrize("key", [k for k, v in EINORDNUNG.items() if v == C])
def test_config_schluessel_im_handbuch(key):
    assert f"`{key}`" in HANDBUCH, key


def test_modules_enabled_im_handbuch():
    assert "`modules.enabled`" in HANDBUCH


def test_jedes_sichtbare_zahlenfeld_hat_einheit_und_hilfe():
    """Sichtbare Zahlenfelder: Einheit im Feld und Hilfetext; erweiterte: Hilfetext (der Web-Port hat
    keine Einheit)."""
    for section in settings_schema.SECTIONS:
        for spec in section.fields:
            if spec.unit is not None:
                assert spec.unit in settings_schema.UNITS, spec.key
            if spec.visibility == C or spec.type not in ("int", "float"):
                continue
            assert spec.help.strip(), spec.key
            if spec.visibility == S:
                assert spec.unit, spec.key


def test_rasterweite_in_mm_gespeichert_in_punkten(api):
    client, _ctx = api
    fields = {f["key"]: f for s in client.get("/api/v1/settings").json()["sections"] for f in s["fields"]}
    grid = fields["gui.editor_grid_mm"]
    assert grid["value"] == 1.0          # Standard 8 Punkte = 1 mm
    assert grid["unit"] == "mm"
    assert grid["type"] == "float"
    r = client.patch("/api/v1/settings", json={"changes": {"gui.editor_grid_mm": 2.5}})
    assert r.status_code == 200, r.text
    stored = json.loads(paths.config_path().read_text(encoding="utf-8"))["gui"]
    assert stored["editor_grid_dots"] == 20
    assert "editor_grid_mm" not in stored
    fields = {f["key"]: f for s in r.json()["sections"] for f in s["fields"]}
    assert fields["gui.editor_grid_mm"]["value"] == 2.5
    r = client.patch("/api/v1/settings", json={"changes": {"gui.editor_grid_mm": 9}})
    assert r.status_code == 422
