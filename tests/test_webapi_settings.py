"""Einstellungsschema, Verbindung/Einrichtung, Dienstinfo."""

from __future__ import annotations

import json
import os

import pytest

from tapesmith import config as config_mod
from tapesmith import paths
from tapesmith.transport.btports import BtPort
from tapesmith.webapi import routes_settings
from tapesmith.webapi.settings_schema import FieldSpec, check_field
from webapi_fakes import close_ctx, make_client

SECTION_ORDER = ["verbindung", "drucken", "warteschlange", "editor", "tray", "oberflaeche", "updates",
                 "sicherung", "vorlagen", "archiv", "druckdienst", "ble", "ssh"]


class FakeRunner:
    """Wie tests/test_daemon_web.py: sammelt `reconfigure`-Aufrufe."""

    def __init__(self):
        self.configs: list[dict] = []
        self._auto = True

    def reconfigure(self, cfg):
        self.configs.append(cfg)
        self._auto = bool(config_mod.setting(cfg, "queue.auto_retry"))

    @property
    def auto_retry(self):
        return self._auto

    def next_try(self):
        return None

    def stop(self):
        pass

    probe_name = "auto"
    last_reason = ""


@pytest.fixture
def api(tmp_path):
    client, ctx = make_client(tmp_path)
    yield client, ctx
    close_ctx(ctx)


def _fields(body: dict) -> dict:
    return {f["key"]: f for section in body["sections"] for f in section["fields"]}


# ---------- GET /settings ----------

def test_settings_sections_order_and_values(api):
    client, _ctx = api
    r = client.get("/api/v1/settings")
    assert r.status_code == 200
    body = r.json()
    assert [s["id"] for s in body["sections"]] == SECTION_ORDER
    assert body["config_path"] == str(paths.config_path())

    fields = _fields(body)
    assert fields["queue.auto_retry"]["value"] is True
    assert fields["web.port"]["default"] == 8712
    assert fields["web.port"]["min"] == 1024
    assert fields["web.port"]["max"] == 65535
    assert fields["guard.max_copies"]["default"] == 50


# ---------- PATCH /settings ----------

def test_patch_settings_ok_updates_file_service_and_runner(api):
    client, ctx = api
    runner = FakeRunner()
    ctx.service.attach_runner(runner)
    sub = ctx.broker.subscribe()

    r = client.patch("/api/v1/settings", json={"changes": {"queue.auto_retry": False, "transport": "com4"}})
    assert r.status_code == 200

    data = json.loads(paths.config_path().read_text(encoding="utf-8"))
    assert data["transport"] == "COM4"
    assert data["queue"]["auto_retry"] is False

    assert runner.configs, "Fake-Runner bekam kein reconfigure"
    assert config_mod.setting(runner.configs[-1], "queue.auto_retry") is False
    assert ctx.service.config["queue"]["auto_retry"] is False

    event = sub.get(1.0)
    assert event is not None
    name, payload = event
    assert name == "config"
    assert set(payload["keys"]) == {"queue.auto_retry", "transport"}


def test_patch_web_port_out_of_range_saves_nothing(api):
    client, _ctx = api
    path = paths.config_path()
    before = path.read_bytes()

    r = client.patch("/api/v1/settings", json={"changes": {"web.port": 80}})
    assert r.status_code == 422
    message = r.json()["error"]["message"]
    assert "1024" in message and "65535" in message
    assert path.read_bytes() == before

    r = client.patch("/api/v1/settings", json={"changes": {"web.port": "8712"}})
    assert r.status_code == 422
    assert path.read_bytes() == before

    r = client.patch("/api/v1/settings", json={"changes": {"queue.auto_retry": "ja"}})
    assert r.status_code == 422
    assert path.read_bytes() == before


def test_patch_choice_invalid_and_nullable_ok(api):
    client, _ctx = api
    r = client.patch("/api/v1/settings", json={"changes": {"app.theme": "neon"}})
    assert r.status_code == 422

    r = client.patch("/api/v1/settings", json={"changes": {"gui.screen_px_per_mm": None}})
    assert r.status_code == 200


def test_patch_unknown_key_saves_nothing(api):
    client, _ctx = api
    path = paths.config_path()
    before = path.read_bytes()
    r = client.patch("/api/v1/settings", json={"changes": {"foo.bar": 1}})
    assert r.status_code == 422
    assert path.read_bytes() == before


def test_patch_transport_invalid_uses_check_transport_message(api):
    client, _ctx = api
    r = client.patch("/api/v1/settings", json={"changes": {"transport": "quatsch"}})
    assert r.status_code == 422
    assert "quatsch" in r.json()["error"]["message"]


def test_patch_two_changes_one_invalid_saves_neither(api):
    client, _ctx = api
    path = paths.config_path()
    before = path.read_bytes()
    r = client.patch("/api/v1/settings",
                     json={"changes": {"queue.auto_retry": True, "web.port": 80}})
    assert r.status_code == 422
    assert path.read_bytes() == before


# ---------- check_field (Unit) ----------

def test_check_field_bool_rejects_int():
    spec = FieldSpec("x", "X", "int", min=0, max=10)
    with pytest.raises(ValueError):
        check_field(spec, True)


def test_check_field_integral_float_becomes_int():
    spec = FieldSpec("x", "X", "int", min=0, max=10)
    assert check_field(spec, 5.0) == 5


def test_check_field_none_rejected_when_not_nullable():
    spec = FieldSpec("x", "X", "string")
    with pytest.raises(ValueError):
        check_field(spec, None)


# ---------- GET /settings/ports ----------

def test_settings_ports_contains_auto_ble_and_mocked_port(api, monkeypatch):
    client, _ctx = api
    monkeypatch.setattr(routes_settings, "list_bt_ports",
                        lambda: [BtPort("COM4", "001122334455", True)])
    r = client.get("/api/v1/settings/ports")
    assert r.status_code == 200
    values = [t["value"] for t in r.json()["transports"]]
    assert "auto" in values
    assert "ble" in values
    assert "COM4" in values


# ---------- POST /settings/setup ----------

def test_settings_setup_ok_releases_lease(api, monkeypatch):
    client, ctx = api

    def fake_probe_factory(mac, timeout, profile):
        def probe(port):
            return [(b"\x1f\x11\x08", b"\x1a\x04\x4b")]
        return probe

    monkeypatch.setattr(routes_settings, "PROBE_FACTORY", fake_probe_factory)
    r = client.post("/api/v1/settings/setup", json={"port": "COM4", "test_label": False})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["steps"]
    assert ctx.service.leased is False


def test_settings_setup_busy_when_leased(api):
    client, ctx = api
    lease_id = ctx.service.lease(object(), 60)
    r = client.post("/api/v1/settings/setup", json={"port": "COM4", "test_label": False})
    assert r.status_code == 409
    ctx.service.release(lease_id)


# ---------- GET /daemon ----------

def test_get_daemon(api):
    client, ctx = api
    r = client.get("/api/v1/daemon")
    assert r.status_code == 200
    body = r.json()
    assert body["pid"] == os.getpid()
    assert body["web_port"] == ctx.port
    assert body["home_key"] == ctx.home_key


def test_choice_nimmt_zahl_als_text_an():
    # Die Auswahlliste der Web-Oberfläche schickte "5" statt 5 für die Schneidpause.
    spec = FieldSpec("cut_pause_s", "Schneidpause", "choice", choices=((None, "bis Weiter"), (0, "aus"), (5, "5 s")),
                     nullable=True)
    assert check_field(spec, "5") == 5
    assert check_field(spec, 5) == 5
    with pytest.raises(ValueError):
        check_field(spec, "7")
