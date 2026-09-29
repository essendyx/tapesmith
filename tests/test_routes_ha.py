"""Router /homelab/ha. Kein echter HA-Aufruf, kein echtes Token."""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from homelab_fakes import (
    FakeKeyring,
    connect_error_transport,
    load_json,
    mock_transport,
    router_client,
    token_file,
    write_homelab,
)
from tapesmith.templates.store import find_template
from tapesmith.webapi import batchapi, routes_ha
from webapi_fakes import close_ctx

# Integrationen im Produkt ohne Standardadressen: Tests nutzen neutrale Testadressen.
pytestmark = pytest.mark.usefixtures("homelab_test_defaults")

BATTERIES = load_json("homeassistant/template-batteries.json")


@pytest.fixture
def api(tmp_path):
    ref = token_file(tmp_path, "ha_token")
    write_homelab({"homeassistant": {"token_ref": ref, "todo_entity": None}})
    routes = {"POST /api/template": (200, json.dumps(BATTERIES))}
    client, ctx = router_client(tmp_path, routes_ha.router, extras={
        "keyring_module": FakeKeyring(),
        "transports": {"homeassistant": mock_transport(routes)},
    }, now=lambda: datetime(2026, 9, 28, 12, 0, 0))
    yield client, ctx
    close_ctx(ctx)


def test_get_batteries(api):
    client, _ctx = api
    response = client.get("/api/v1/homelab/ha/batteries")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["todo_entity"] is None
    devices = body["devices"]
    assert {d["device"] for d in devices} == {
        "Fensterkontakt Bad", "Bewegungsmelder Flur", "Thermostat Wohnzimmer",
        "Rauchmelder Flur", "Feuchtesensor Keller",
    }


def test_get_batteries_below_filters(api):
    client, _ctx = api
    response = client.get("/api/v1/homelab/ha/batteries", params={"below": 50})
    assert response.status_code == 200
    devices = response.json()["devices"]
    assert {d["device"] for d in devices} == {"Fensterkontakt Bad", "Bewegungsmelder Flur"}


def test_get_batteries_not_reachable(tmp_path):
    ref = token_file(tmp_path, "ha_token")
    write_homelab({"homeassistant": {"token_ref": ref}})
    client, ctx = router_client(tmp_path, routes_ha.router, extras={
        "keyring_module": FakeKeyring(),
        "transports": {"homeassistant": connect_error_transport()},
    })
    try:
        response = client.get("/api/v1/homelab/ha/batteries")
        assert response.status_code == 503
    finally:
        close_ctx(ctx)


def test_put_battery_type(api):
    client, _ctx = api
    response = client.put("/api/v1/homelab/ha/battery-type",
                          json={"entity_id": "sensor.wohnzimmer_thermostat_battery", "battery_type": "AA"})
    assert response.status_code == 200
    assert response.json() == {"ok": True}

    response = client.get("/api/v1/homelab/ha/batteries")
    thermostat = next(d for d in response.json()["devices"] if d["device"] == "Thermostat Wohnzimmer")
    assert thermostat["battery_type"] == "AA"
    assert thermostat["type_source"] == "lokal"


def test_post_table_builds_pending_with_datum_and_warns_missing_type(api):
    client, ctx = api
    response = client.post("/api/v1/homelab/ha/table", json={
        "entity_ids": ["sensor.flur_bewegung_battery", "sensor.wohnzimmer_thermostat_battery"],
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["template"] == "batterie"
    assert body["count"] == 2
    assert any("Thermostat Wohnzimmer" in w for w in body["warnings"])

    template = find_template("batterie")
    rows, mapping, headers = batchapi.build_rows(
        ctx, template, {"type": "pending", "id": body["pending_id"]}, None, None, None)
    assert headers == ["geraet", "raum", "typ", "datum"]
    assert mapping["datum"] == "datum"
    plan = batchapi.plan(ctx, template, rows)
    bewegung_row = next(r for r in rows if r["geraet"] == "Bewegungsmelder Flur")
    assert bewegung_row["datum"] == "28.09.2026"
    assert bewegung_row["typ"] == "CR2450"
    # Thermostat-Zeile ohne Typ meldet den Pflichtfehler, Bewegungsmelder-Zeile ist fehlerfrei
    assert any("fehlt" in e for e in plan.errors)
    assert plan.rows[rows.index(bewegung_row)].render is not None


def test_post_todo_without_entity_is_424(api):
    client, _ctx = api
    response = client.post("/api/v1/homelab/ha/todo",
                           json={"item": "USV-Akku wechseln", "due": "2029-09-28"})
    assert response.status_code == 424
    body = response.json()["error"]
    assert "todo_entity" in body["message"]


def test_post_todo_with_entity(tmp_path):
    ref = token_file(tmp_path, "ha_token")
    write_homelab({"homeassistant": {"token_ref": ref, "todo_entity": "todo.hausaufgaben"}})
    calls: list = []
    routes = {"POST /api/services/todo/add_item": (200, {})}
    client, ctx = router_client(tmp_path, routes_ha.router, extras={
        "keyring_module": FakeKeyring(),
        "transports": {"homeassistant": mock_transport(routes, calls=calls)},
    })
    try:
        response = client.post("/api/v1/homelab/ha/todo",
                               json={"item": "USV-Akku wechseln", "due": "2029-09-28"})
        assert response.status_code == 200, response.text
        assert response.json() == {"ok": True, "entity_id": "todo.hausaufgaben"}
        assert len(calls) == 1
        body = json.loads(calls[0].content)
        assert body["entity_id"] == "todo.hausaufgaben"
        assert body["due_date"] == "2029-09-28"
    finally:
        close_ctx(ctx)
