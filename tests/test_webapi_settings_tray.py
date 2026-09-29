"""Tray und Tastenkürzel werden nur noch in der Web-Oberfläche eingestellt (kein Tray-Dialog mehr).

Jede Einstellung des früheren Tray-Einstellungsdialogs steht im Einstellungsschema (Abschnitt
„tray“, Autostart unter Windows-Integration); die Prüfungen des Dialogs (gültiges Kürzel, kein
AltGr-Zeichen, zwei verschiedene Kürzel, Normalform) laufen jetzt beim Speichern über
`PATCH /api/v1/settings`. Die Tray-App übernimmt die Werte ohne Neustart (kein `restart`)."""

from __future__ import annotations

import json

import pytest

from tapesmith import paths
from tapesmith.hotkeyspec import GERMAN_ALTGR, FakeLayoutProbe
from tapesmith.webapi import settings_schema
from webapi_fakes import close_ctx, make_client


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_schema, "layout_probe", lambda: FakeLayoutProbe(GERMAN_ALTGR))
    client, ctx = make_client(tmp_path)
    yield client, ctx
    close_ctx(ctx)


def _tray_fields(client) -> dict:
    body = client.get("/api/v1/settings").json()
    section = next(s for s in body["sections"] if s["id"] == "tray")
    return {f["key"]: f for f in section["fields"]}


def test_alle_frueheren_dialog_einstellungen_in_der_web_oberflaeche(api):
    client, _ctx = api
    fields = _tray_fields(client)
    assert set(fields) == {"hotkey.enabled", "hotkey.quick", "hotkey.clipboard", "tray.notify", "tray.favorites"}
    assert fields["hotkey.quick"]["type"] == "hotkey"
    assert fields["hotkey.quick"]["value"] == "Ctrl+Alt+L"
    # Tray-App liest die Datei laufend: kein Neustart-Hinweis
    assert not any(f.get("restart") for f in fields.values())
    # Autostart der Tray-App: Windows-Integration der Web-Oberfläche
    status = client.get("/api/v1/integration").json()["status"]
    assert "autostart" in status


def test_toast_dauer_entfaellt():
    keys = {f.key for s in settings_schema.SECTIONS for f in s.fields}
    assert "tray.toast_s" not in keys


def test_kuerzel_wird_normalisiert_gespeichert(api):
    client, _ctx = api
    r = client.patch("/api/v1/settings", json={"changes": {"hotkey.quick": "ctrl+alt+k",
                                                           "hotkey.clipboard": "win+shift+f9"}})
    assert r.status_code == 200, r.text
    data = json.loads(paths.config_path().read_text(encoding="utf-8"))
    assert data["hotkey"] == {"quick": "Strg+Alt+K", "clipboard": "Umschalt+Win+F9"}


@pytest.mark.parametrize("value, text", [
    ("Ctrl+Alt+Q", "@"),                 # AltGr auf deutscher Tastatur
    ("L", "Strg, Alt oder Win"),
    ("Strg+Alt+ÄÖ", "nicht erlaubt"),
    ("Win+L", "sperrt Windows"),
    (5, "Text"),
])
def test_ungueltiges_kuerzel_speichert_nichts(api, value, text):
    client, _ctx = api
    path = paths.config_path()
    before = path.read_bytes()
    r = client.patch("/api/v1/settings", json={"changes": {"hotkey.quick": value}})
    assert r.status_code == 422
    assert text in r.json()["error"]["message"]
    assert path.read_bytes() == before


def test_gleiche_kuerzel_werden_abgelehnt(api):
    client, _ctx = api
    path = paths.config_path()
    before = path.read_bytes()
    r = client.patch("/api/v1/settings", json={"changes": {"hotkey.clipboard": "Strg+Alt+L"}})
    assert r.status_code == 422
    assert "verschiedene" in r.json()["error"]["message"]
    assert path.read_bytes() == before


def test_ohne_windows_keine_altgr_pruefung(monkeypatch):
    monkeypatch.setattr(settings_schema, "layout_probe", lambda: None)
    assert settings_schema.check_hotkey("Schnelldruck", "Ctrl+Alt+Q") == "Strg+Alt+Q"
