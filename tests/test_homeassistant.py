"""Home-Assistant-Client (Batterien). Kein echter HA-Aufruf, kein echtes Token:
immer `httpx.MockTransport` und `token_file(...)`."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from homelab_fakes import connect_error_transport, load_json, mock_transport, token_file
from tapesmith.integrations import homeassistant as ha
from tapesmith.integrations.errors import AuthFailed, NotReachable, TokenMissing, UpstreamError
from tapesmith.templates.fill import CounterStore, input_fields, resolve_values
from tapesmith.templates.store import find_template

BATTERIES = load_json("homeassistant/template-batteries.json")
EMPTY = load_json("homeassistant/template-empty.json")


def _client(routes, tmp_path, *, token="test-token-123"):
    ref = token_file(tmp_path, "ha_token", token)
    from tapesmith.integrations import credentials

    tok = credentials.read_secret(ref, what="Home Assistant")
    return ha.HaClient("http://192.0.2.9:8123", tok, transport=mock_transport(routes))


# ---------- batteries() ----------

def test_batteries_sends_authorization_and_template(tmp_path):
    calls: list = []
    import json as jsonmod

    routes = {"POST /api/template": (200, jsonmod.dumps(BATTERIES))}
    ref = token_file(tmp_path, "ha_token", "test-token-123")
    from tapesmith.integrations import credentials

    token = credentials.read_secret(ref, what="Home Assistant")
    transport = mock_transport(routes, calls=calls)
    client = ha.HaClient("http://192.0.2.9:8123", token, transport=transport)

    result = client.batteries()

    assert len(calls) == 1
    request = calls[0]
    assert request.headers["Authorization"] == "Bearer test-token-123"
    import json as jsonmod2

    assert jsonmod2.loads(request.content) == {"template": ha.BATTERY_TEMPLATE}
    assert result == BATTERIES


def test_batteries_html_instead_of_json_is_upstream_error(tmp_path):
    routes = {"POST /api/template": (200, "<html>nope</html>")}
    client = _client(routes, tmp_path)
    with pytest.raises(UpstreamError):
        client.batteries()


def test_batteries_not_reachable(tmp_path):
    ref = token_file(tmp_path, "ha_token")
    from tapesmith.integrations import credentials

    token = credentials.read_secret(ref, what="Home Assistant")
    client = ha.HaClient("http://192.0.2.9:8123", token, transport=connect_error_transport())
    with pytest.raises(NotReachable):
        client.batteries()


# ---------- parse_devices ----------

def test_parse_devices_dedupes_and_sorts(tmp_path):
    types = ha.BatteryTypes(tmp_path / "batterietypen.json")
    devices = ha.parse_devices(BATTERIES, types)

    names = [d.device for d in devices]
    assert names.count("Thermostat Wohnzimmer") == 1
    # schwach zuerst (binary_sensor "on" bzw. level < 20), danach aufsteigend nach Batteriestand
    assert [d.device for d in devices if d.low] == ["Bewegungsmelder Flur", "Fensterkontakt Bad"]
    assert devices[0].device == "Bewegungsmelder Flur"
    levels = [d.level for d in devices if d.level is not None]
    assert levels == sorted(levels)


def test_parse_devices_unavailable_is_none(tmp_path):
    types = ha.BatteryTypes(tmp_path / "batterietypen.json")
    devices = ha.parse_devices(BATTERIES, types)
    keller = next(d for d in devices if d.device == "Feuchtesensor Keller")
    assert keller.level is None


def test_parse_devices_local_type_with_ha_priority(tmp_path):
    types = ha.BatteryTypes(tmp_path / "batterietypen.json")
    types.set("sensor.wohnzimmer_thermostat_battery", "AA")
    devices = ha.parse_devices(BATTERIES, types)

    thermostat = next(d for d in devices if d.device == "Thermostat Wohnzimmer")
    assert thermostat.battery_type == "AA"
    assert thermostat.type_source == "lokal"

    bewegung = next(d for d in devices if d.device == "Bewegungsmelder Flur")
    assert bewegung.battery_type == "CR2450"
    assert bewegung.type_source == "Home Assistant"


def test_parse_devices_below_filters(tmp_path):
    types = ha.BatteryTypes(tmp_path / "batterietypen.json")
    devices = ha.parse_devices(BATTERIES, types, below=50)
    names = {d.device for d in devices}
    assert names == {"Fensterkontakt Bad", "Bewegungsmelder Flur"}


def test_parse_devices_empty(tmp_path):
    types = ha.BatteryTypes(tmp_path / "batterietypen.json")
    assert ha.parse_devices(EMPTY, types) == []


# ---------- BatteryTypes ----------

def test_battery_types_roundtrip_and_remove(tmp_path):
    types = ha.BatteryTypes(tmp_path / "batterietypen.json")
    assert types.get("sensor.x") is None
    types.set("sensor.x", "CR2032")
    assert types.get("sensor.x") == "CR2032"
    assert types.all() == {"sensor.x": "CR2032"}
    types.set("sensor.x", None)
    assert types.get("sensor.x") is None
    assert types.all() == {}


def test_battery_types_too_long_is_value_error(tmp_path):
    types = ha.BatteryTypes(tmp_path / "batterietypen.json")
    with pytest.raises(ValueError):
        types.set("sensor.x", "X" * 25)


# ---------- Daten/Fälligkeit ----------

def test_due_date_caps_day():
    assert ha.due_date(date(2026, 1, 31), 1) == date(2026, 2, 28)


def test_maintenance_values_zero_months_is_value_error():
    with pytest.raises(ValueError):
        ha.maintenance_values("USV-Akku", day=date(2026, 9, 28), months=0)


# ---------- add_todo ----------

def test_add_todo_sends_due_date(tmp_path):
    calls: list = []
    routes = {"POST /api/services/todo/add_item": (200, {})}
    ref = token_file(tmp_path, "ha_token", "test-token-123")
    from tapesmith.integrations import credentials

    token = credentials.read_secret(ref, what="Home Assistant")
    transport = mock_transport(routes, calls=calls)
    client = ha.HaClient("http://192.0.2.9:8123", token, transport=transport)

    client.add_todo("todo.hausaufgaben", "USV-Akku wechseln", due=date(2029, 9, 28), description="Notiz")

    assert len(calls) == 1
    import json as jsonmod

    body = jsonmod.loads(calls[0].content)
    assert body == {"entity_id": "todo.hausaufgaben", "item": "USV-Akku wechseln",
                    "due_date": "2029-09-28", "description": "Notiz"}


def test_add_todo_401_is_auth_failed(tmp_path):
    routes = {"POST /api/services/todo/add_item": (401, {})}
    client = _client(routes, tmp_path)
    with pytest.raises(AuthFailed):
        client.add_todo("todo.x", "Item")


def test_add_todo_missing_token_file_is_token_missing(tmp_path):
    missing_ref = f"file:{tmp_path / 'no-such-file'}"
    with pytest.raises(TokenMissing) as excinfo:
        from tapesmith.integrations import credentials

        credentials.read_secret(missing_ref, what="Home Assistant")
    assert "Home Assistant" in str(excinfo.value)


# ---------- Druckbarkeit der Werte-Dicts ----------

def test_battery_values_are_printable(tmp_path):
    template = find_template("batterie")
    dev = ha.BatteryDevice(entity_id="sensor.x", device="Fensterkontakt Bad", area="Bad", level=None,
                           low=True, battery_type="CR2032", type_source="Home Assistant")
    values = ha.battery_values(dev, day=date(2026, 9, 28))
    assert set(values) == {"geraet", "raum", "typ", "datum"}
    assert set(values) <= {f.id for f in input_fields(template)}
    assert template.field("datum").type == "input"

    counters = CounterStore(tmp_path / "counters.json")
    resolved = resolve_values(template, values, datetime(2026, 9, 28), counters)
    assert resolved.values["datum"] == "28.09.2026"


def test_maintenance_values_are_printable(tmp_path):
    template = find_template("wartung")
    values = ha.maintenance_values("USV-Akku", day=date(2026, 9, 28), months=36)
    assert set(values) == {"was", "datum", "intervall", "notiz"}
    assert set(values) <= {f.id for f in input_fields(template)}

    counters = CounterStore(tmp_path / "counters.json")
    resolved = resolve_values(template, values, datetime(2026, 9, 28), counters)
    assert resolved.values["datum"] == "28.09.2026"
    assert resolved.values["naechste"] == "28.09.2029"
