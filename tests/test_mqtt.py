"""MQTT-Bridge (Home-Assistant-Discovery, Zustand, Druck) mit Fake-Client und `FakeFacade`."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from automation_fakes import FakeClock, FakeFacade, queue_json, queued_job, status_json
from tapesmith import secretref
from tapesmith.automation import mqtt
from webapi_fakes import close_ctx, make_ctx

PW = "pw"


class FakeMqttMessage:
    def __init__(self, topic: str, payload):
        self.topic = topic
        self.payload = payload.encode("utf-8") if isinstance(payload, str) else payload


class FakeMqttClient:
    """Zeichnet die paho-Aufrufe auf, verbindet sich zu nichts."""

    def __init__(self, client_id=None):
        self.client_id = client_id
        self.username = None
        self.password = None
        self.will = None
        self.reconnect_delay = None
        self.tls = False
        self.connect_async_args = None
        self.loop_started = False
        self.loop_stopped = False
        self.disconnected = False
        self.published: list[tuple[str, object, int, bool]] = []
        self.subscribed: list[tuple[str, int]] = []
        self.on_connect = None
        self.on_message = None
        self.on_disconnect = None

    def username_pw_set(self, username, password=None):
        self.username = username
        self.password = password

    def will_set(self, topic, payload=None, qos=0, retain=False, properties=None):
        self.will = (topic, payload, qos, retain)

    def reconnect_delay_set(self, min_delay=1, max_delay=120):
        self.reconnect_delay = (min_delay, max_delay)

    def tls_set(self, *a, **kw):
        self.tls = True

    def connect_async(self, host, port=1883, keepalive=60, **kw):
        self.connect_async_args = (host, port, keepalive)

    def loop_start(self):
        self.loop_started = True

    def loop_stop(self):
        self.loop_stopped = True

    def disconnect(self):
        self.disconnected = True

    def publish(self, topic, payload=None, qos=0, retain=False, properties=None):
        self.published.append((topic, payload, qos, retain))

    def subscribe(self, topic, qos=0, **kw):
        self.subscribed.append((topic, qos))


def _bridge(facade, cfg=None, *, clock=None, secret_reader=None, hostname="PC1"):
    created: list[FakeMqttClient] = []

    def factory(client_id):
        client = FakeMqttClient(client_id)
        created.append(client)
        return client

    reader = secret_reader if secret_reader is not None else (lambda ref, **kw: PW)
    bridge = mqtt.MqttBridge(facade, cfg if cfg is not None else {"mqtt": {"enabled": True, "host": "192.0.2.9"}},
                             client_factory=factory, secret_reader=reader,
                             clock=clock or FakeClock(), hostname=hostname)
    return bridge, created


def _connect(bridge, created):
    bridge.start()
    client = created[-1]
    client.on_connect(client, None, {}, 0, None)
    return client


def _wait(predicate, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert predicate(), "Zeitüberschreitung beim Warten auf den Worker"


def _results(client: FakeMqttClient, bridge: mqtt.MqttBridge) -> list[dict]:
    return [json.loads(p) for t, p, _q, _r in client.published if t == bridge._topic_print_result()]


def _last_result(client: FakeMqttClient, bridge: mqtt.MqttBridge) -> dict:
    _wait(lambda: _results(client, bridge))
    return _results(client, bridge)[-1]


# ---------- create ----------

def test_create_aus_ist_none():
    assert mqtt.create(FakeFacade(), {"mqtt": {"enabled": False}}) is None
    assert mqtt.create(FakeFacade(), {}) is None


def test_create_an_liefert_bridge():
    addon = mqtt.create(FakeFacade(), {"mqtt": {"enabled": True, "host": "192.0.2.9"}})
    assert isinstance(addon, mqtt.MqttBridge)
    assert addon.name == "mqtt"


# ---------- start ----------

def test_start_verbindet_mit_secret():
    facade = FakeFacade()
    bridge, created = _bridge(facade)
    try:
        bridge.start()
        client = created[-1]
        assert client.username == "tapesmith"
        assert client.password == PW
        assert client.will == ("tapesmith/availability", "offline", 0, True)
        assert client.connect_async_args == ("192.0.2.9", 1883, 60)
        assert client.loop_started is True
    finally:
        bridge.stop()


def test_start_secret_fehlt_kein_connect():
    def reader(ref, **kw):
        raise secretref.SecretMissing("Kein Wert in den Windows-Anmeldeinformationen für tapesmith/mqtt")

    facade = FakeFacade()
    bridge, created = _bridge(facade, secret_reader=reader)
    bridge.start()
    assert created == []
    st = bridge.status()
    assert st["running"] is False
    assert "tapesmith/mqtt" in st["error"]
    bridge.stop()  # darf ohne laufenden Client nicht scheitern


# ---------- on_connect: Discovery, Verfügbarkeit, Zustand, Abos ----------

def test_on_connect_discovery_online_zustand_abos():
    facade = FakeFacade()
    bridge, created = _bridge(facade)
    try:
        client = _connect(bridge, created)

        config_topics = {t for t, _p, _q, _r in client.published if t.endswith("/config")}
        assert config_topics == {
            "homeassistant/binary_sensor/tapesmith/verbindung/config",
            "homeassistant/sensor/tapesmith/akku/config",
            "homeassistant/binary_sensor/tapesmith/deckel/config",
            "homeassistant/sensor/tapesmith/warteschlange/config",
            "homeassistant/button/tapesmith/testlabel/config",
        }
        for topic, payload, _qos, retain in client.published:
            if topic.endswith("/config"):
                assert retain is True
                json.loads(payload)  # gültiges JSON

        online = [(p, r) for t, p, _q, r in client.published if t == "tapesmith/availability"]
        assert online[-1] == ("online", True)

        state_msgs = [(p, r) for t, p, _q, r in client.published if t == "tapesmith/state"]
        assert state_msgs
        payload, retain = state_msgs[-1]
        assert retain is True
        data = json.loads(payload)
        assert set(data) == {"connected", "battery", "lid_open", "queue"}
        assert data["connected"] is True

        assert ("tapesmith/print/set", 1) in client.subscribed
        assert ("tapesmith/test/press", 1) in client.subscribed
    finally:
        bridge.stop()


def test_unverifizierte_entitaeten_leerer_payload():
    facade = FakeFacade(verified=("media",))
    bridge, created = _bridge(facade)
    try:
        client = _connect(bridge, created)
        by_topic = {t: p for t, p, _q, _r in client.published}
        assert by_topic["homeassistant/sensor/tapesmith/akku/config"] == ""
        assert by_topic["homeassistant/binary_sensor/tapesmith/deckel/config"] == ""

        state = json.loads(by_topic["tapesmith/state"])
        assert state["battery"] is None
        assert state["lid_open"] is None
    finally:
        bridge.stop()


def test_discovery_payloads_eindeutig_und_gueltig():
    facade = FakeFacade()
    bridge, _created = _bridge(facade)
    messages = bridge.discovery_messages()
    unique_ids = []
    device_ids = None
    for topic, payload, retain in messages:
        assert retain is True
        assert payload is not None
        json.dumps(payload)
        assert payload["unique_id"] not in unique_ids
        unique_ids.append(payload["unique_id"])
        assert payload["availability_topic"] == "tapesmith/availability"
        if device_ids is None:
            device_ids = payload["device"]["identifiers"]
        else:
            assert payload["device"]["identifiers"] == device_ids
    assert device_ids == ["tapesmith_PC1"]


def test_deckel_value_template_meldet_unbekannt_bei_null():
    """Ein unbekannter Deckelzustand (`lid_open: null`) darf in Home Assistant nicht als OFF
    ankommen, sondern muss unbekannt (None) bleiben."""
    facade = FakeFacade()
    bridge, _created = _bridge(facade)
    by_topic = {t: p for t, p, _r in bridge.discovery_messages()}
    template = by_topic["homeassistant/binary_sensor/tapesmith/deckel/config"]["value_template"]
    assert "is none" in template
    assert "{{ none }}" in template
    assert "'ON' if value_json.lid_open else 'OFF'" in template


# ---------- Zustand: Statuswerte über den festgelegten Pfad ----------

def test_state_payload_status_none():
    facade = FakeFacade(status=status_json(status_none=True))
    bridge, _created = _bridge(facade)
    payload = bridge.state_payload()
    assert payload["battery"] is None
    assert payload["lid_open"] is None


@pytest.mark.parametrize("lid, expected", [("offen", True), ("zu", False)])
def test_state_payload_deckel_invertierung(lid, expected):
    facade = FakeFacade(status=status_json(lid=lid))
    bridge, _created = _bridge(facade)
    assert bridge.state_payload()["lid_open"] is expected


def test_state_payload_deckel_aus_echtem_profil():
    from tapesmith.device.profile import load_profile
    from tapesmith.protocol.status import decode

    profile = load_profile()
    codes = profile.status_map()
    msg = decode(bytes.fromhex("1a0599"), codes)[0]
    assert msg.value == "offen"

    facade = FakeFacade(status=status_json(lid=msg.value))
    bridge, _created = _bridge(facade)
    assert bridge.state_payload()["lid_open"] is True


@pytest.mark.parametrize("battery, expected", [(75, 75), (200, None), (None, None)])
def test_state_payload_akku(battery, expected):
    facade = FakeFacade(status=status_json(battery=battery))
    bridge, _created = _bridge(facade)
    assert bridge.state_payload()["battery"] == expected


def test_state_payload_echte_fassade(tmp_path):
    from tapesmith.automation.facade import LabelFacade

    ctx = make_ctx(tmp_path)
    try:
        facade = LabelFacade.from_ctx(ctx)
        bridge, _created = _bridge(facade)
        payload = bridge.state_payload()
        assert set(payload) == {"connected", "battery", "lid_open", "queue"}
    finally:
        close_ctx(ctx)


def test_state_payload_warteschlange_zaehlt_wartend_und_laufend():
    facade = FakeFacade(queue=queue_json([
        queued_job(1), queued_job(2, state="läuft"), queued_job(3, state="fertig"),
    ]))
    bridge, _created = _bridge(facade)
    assert bridge.state_payload()["queue"] == 2


# ---------- Ereignisse: Entprellung ----------

def test_ereignis_gleicher_inhalt_nicht_doppelt():
    facade = FakeFacade()
    clock = FakeClock()
    bridge, created = _bridge(facade, clock=clock)
    try:
        client = _connect(bridge, created)
        count_before = len(client.published)
        facade.emit("queue", {})  # unveränderter Inhalt
        assert len(client.published) == count_before

        facade.queue_value = queue_json([queued_job(1)])  # Inhalt ändert sich
        facade.emit("queue", {})
        # innerhalb einer Sekunde (fake Uhr steht still): noch nicht gesendet
        assert len(client.published) == count_before

        clock.advance(1.1)
        _wait(lambda: len(client.published) > count_before)
        state_msgs = [json.loads(p) for t, p, _q, _r in client.published if t == "tapesmith/state"]
        assert state_msgs[-1]["queue"] == 1
    finally:
        bridge.stop()


# ---------- Druck über print/set ----------

def test_on_message_print_set_druckt_einmal_im_worker():
    facade = FakeFacade()
    bridge, created = _bridge(facade)
    try:
        client = _connect(bridge, created)
        client.published.clear()
        msg = FakeMqttMessage(bridge._topic_print_set(),
                              json.dumps({"template": "gefriergut", "values": {"inhalt": "Suppe"}, "copies": 2}))
        client.on_message(client, None, msg)

        _wait(lambda: facade.printed)
        assert len(facade.printed) == 1
        source, options, origin = facade.printed[0]
        assert origin == "mqtt"
        assert source == {"kind": "template", "template": "gefriergut", "values": {"inhalt": "Suppe"}}
        assert options == {"copies": 2}

        result = _last_result(client, bridge)
        assert result["status"] == "ok"
    finally:
        bridge.stop()


def test_on_message_vorlage_nicht_freigegeben():
    facade = FakeFacade()
    bridge, created = _bridge(facade, cfg={"mqtt": {"enabled": True, "host": "192.0.2.9", "templates": ["eigentum"]}})
    try:
        client = _connect(bridge, created)
        client.published.clear()
        msg = FakeMqttMessage(bridge._topic_print_set(), json.dumps({"template": "gefriergut", "values": {}}))
        client.on_message(client, None, msg)

        result = _last_result(client, bridge)
        assert result["status"] == "abgelehnt"
        assert facade.printed == []
    finally:
        bridge.stop()


@pytest.mark.parametrize("payload", [
    b"kein json",
    json.dumps({"copies": 5}),  # Vorlage fehlt
    json.dumps({"template": "gefriergut", "copies": 6}),
    json.dumps({"template": "gefriergut", "copies": 0}),
    json.dumps({"template": "gefriergut", "copies": True}),
])
def test_on_message_ungueltig_wird_abgelehnt(payload):
    facade = FakeFacade()
    bridge, created = _bridge(facade)
    try:
        client = _connect(bridge, created)
        client.published.clear()
        client.on_message(client, None, FakeMqttMessage(bridge._topic_print_set(), payload))
        result = _last_result(client, bridge)
        assert result["status"] == "abgelehnt"
        assert facade.printed == []
    finally:
        bridge.stop()


def test_on_message_copies_5_wird_gedruckt():
    facade = FakeFacade()
    bridge, created = _bridge(facade)
    try:
        client = _connect(bridge, created)
        client.on_message(client, None, FakeMqttMessage(
            bridge._topic_print_set(), json.dumps({"template": "gefriergut", "copies": 5})))
        _wait(lambda: facade.printed)
        assert facade.printed[0][1]["copies"] == 5
    finally:
        bridge.stop()


def test_on_message_copies_ganzzahliger_float_wird_akzeptiert():
    """Home Assistants Nummern-Selektor liefert im Skript-Template ohne Filter eine Gleitkomma-
    zahl (1.0 statt 1); die soll als ganze Zahl gelten, nicht als ungueltig abgelehnt werden."""
    facade = FakeFacade()
    bridge, created = _bridge(facade)
    try:
        client = _connect(bridge, created)
        client.on_message(client, None, FakeMqttMessage(
            bridge._topic_print_set(), json.dumps({"template": "gefriergut", "copies": 1.0})))
        _wait(lambda: facade.printed)
        copies = facade.printed[0][1]["copies"]
        assert copies == 1
        assert isinstance(copies, int) and not isinstance(copies, bool)
    finally:
        bridge.stop()


def test_on_message_copies_nicht_ganzzahliger_float_wird_abgelehnt():
    facade = FakeFacade()
    bridge, created = _bridge(facade)
    try:
        client = _connect(bridge, created)
        client.published.clear()
        client.on_message(client, None, FakeMqttMessage(
            bridge._topic_print_set(), json.dumps({"template": "gefriergut", "copies": 1.5})))
        result = _last_result(client, bridge)
        assert result["status"] == "abgelehnt"
        assert facade.printed == []
    finally:
        bridge.stop()


def test_on_message_hoehere_grenze_ueber_guard_confirm_copies():
    facade = FakeFacade(config={"guard": {"confirm_copies": 8}})
    bridge, created = _bridge(facade)
    try:
        client = _connect(bridge, created)
        client.on_message(client, None, FakeMqttMessage(
            bridge._topic_print_set(), json.dumps({"template": "gefriergut", "copies": 6})))
        _wait(lambda: facade.printed)
        assert facade.printed[0][1]["copies"] == 6
    finally:
        bridge.stop()


def test_on_message_bestaetigung_noetig_kein_zweiter_versuch():
    from automation_fakes import DEFAULT_OUTCOME

    outcome = dict(DEFAULT_OUTCOME)
    outcome["status"] = "bestätigung_nötig"
    outcome["reasons"] = ["Band passt nicht zur Vorlage"]
    facade = FakeFacade(outcome=outcome)
    bridge, created = _bridge(facade)
    try:
        client = _connect(bridge, created)
        client.on_message(client, None, FakeMqttMessage(
            bridge._topic_print_set(), json.dumps({"template": "gefriergut"})))
        result = _last_result(client, bridge)
        assert result["status"] == "bestätigung_nötig"
        assert "Band passt nicht zur Vorlage" in result["message"]
        time.sleep(0.1)
        assert len(facade.printed) == 1
    finally:
        bridge.stop()


def test_test_press_druckt_mit_kind_test():
    facade = FakeFacade()
    bridge, created = _bridge(facade)
    try:
        client = _connect(bridge, created)
        client.on_message(client, None, FakeMqttMessage(bridge._topic_test_press(), b"beliebig"))
        _wait(lambda: facade.printed)
        source, _options, origin = facade.printed[0]
        assert source == {"kind": "test"}
        assert origin == "mqtt"
    finally:
        bridge.stop()


def test_druckfehler_ergebnis_fehler_worker_laeuft_weiter():
    facade = FakeFacade()
    facade.raise_on_print = RuntimeError("Drucker kaputt")
    bridge, created = _bridge(facade)
    try:
        client = _connect(bridge, created)
        client.on_message(client, None, FakeMqttMessage(
            bridge._topic_print_set(), json.dumps({"template": "gefriergut"})))
        result = _last_result(client, bridge)
        assert result["status"] == "fehler"
        assert "Drucker kaputt" in result["message"]

        facade.raise_on_print = None
        client.published.clear()
        client.on_message(client, None, FakeMqttMessage(bridge._topic_test_press(), b"x"))
        _wait(lambda: len(facade.printed) == 2)
        second = _last_result(client, bridge)
        assert second["status"] == "ok"
    finally:
        bridge.stop()


# ---------- stop ----------

# ---------- deploy/homeassistant: YAML-Dateien ----------

def test_homeassistant_yaml_dateien_enthalten_print_set_kein_geheimnis():
    root = Path(__file__).resolve().parents[1] / "deploy" / "homeassistant"
    yaml_files = sorted(root.glob("*.yaml"))
    assert yaml_files, "keine YAML-Dateien unter deploy/homeassistant gefunden"

    found_print_set = False
    for path in yaml_files:
        text = path.read_text(encoding="utf-8")
        if "tapesmith/print/set" in text:
            found_print_set = True
        for token in ("password:", "token:", "passwort:"):
            for line in text.splitlines():
                if token in line.lower():
                    value = line.split(":", 1)[1].strip()
                    # "{{ ... }}": erst zur Laufzeit ausgewertete Jinja-Vorlage (MQTT-Payload).
                    # "!secret ...": Home Assistants eingebaute Verweis-Syntax auf secrets.yaml
                    # (rest_command-Kopfzeilen), dieselbe Indirektion wie bei den Jinja-Vorlagen.
                    assert (value in ("", "{{ }}") or value.startswith("{{")
                           or value.startswith("!secret ")), (
                        f"möglicher Geheimwert in {path.name}: {line!r}")
    assert found_print_set


def test_homeassistant_rest_command_beispiel_vorhanden():
    """Ein rest_command-Beispiel gehört zur Home-Assistant-Anbindung: direkter REST-Aufruf
    der Kurzendpunkte als Alternative zu MQTT, mit dem Token aus secrets.yaml."""
    path = Path(__file__).resolve().parents[1] / "deploy" / "homeassistant" / "tapesmith-rest-command.yaml"
    text = path.read_text(encoding="utf-8")
    assert "rest_command:" in text
    assert "/api/v1/print" in text
    assert "X-P12-Token: !secret" in text
    assert "kopien | int" in text


def test_homeassistant_skript_uebergibt_kopien_als_ganze_zahl():
    """Der Nummern-Selektor liefert im Template eine Gleitkommazahl (1.0); ohne den int-Filter
    wuerde der Druckdienst das JSON-Feld copies als 1.0 sehen und ablehnen (sourcelimits)."""
    path = Path(__file__).resolve().parents[1] / "deploy" / "homeassistant" / "tapesmith-skript.yaml"
    text = path.read_text(encoding="utf-8")
    assert "kopien | int" in text


def test_stop_sendet_offline_und_beendet_worker():
    facade = FakeFacade()
    bridge, created = _bridge(facade)
    client = _connect(bridge, created)
    worker = bridge._worker
    assert worker is not None and worker.is_alive()

    bridge.stop()

    assert client.disconnected is True
    assert client.loop_stopped is True
    offline = [(p, r) for t, p, _q, r in client.published
              if t == "tapesmith/availability" and p == "offline"]
    assert offline and offline[-1] == ("offline", True)
    assert not worker.is_alive()
