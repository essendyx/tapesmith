"""Tests für `p12 mqtt discovery|status` (über `tapesmith.cli.main`)."""

from __future__ import annotations

import json

from tapesmith import cli
from tapesmith.cli_cmds import mqtt as cli_mqtt


class _FakeKeyring:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service, user):
        return self.values.get((service, user))

    def set_password(self, service, user, value):
        self.values[(service, user)] = value


def test_mqtt_discovery_zeigt_json_ohne_verbindung(app_home, monkeypatch, capsys):
    def _fail_factory(*_a, **_kw):
        raise AssertionError("MqttBridge.discovery darf keine paho-Client-Fabrik aufrufen")

    monkeypatch.setattr("paho.mqtt.client.Client", _fail_factory, raising=False)

    assert cli.main(["mqtt", "discovery"]) == 0
    out = capsys.readouterr().out
    messages = json.loads(out)
    assert isinstance(messages, list)
    topics = {m["topic"] for m in messages}
    assert "homeassistant/button/tapesmith/testlabel/config" in topics
    for m in messages:
        assert set(m) == {"topic", "payload"}


def test_mqtt_status_zeigt_broker_und_referenz_nie_passwort(app_home, monkeypatch, capsys):
    fake = _FakeKeyring()
    monkeypatch.setattr(cli_mqtt, "KEYRING", fake)
    app_home.mkdir(parents=True, exist_ok=True)
    (app_home / "config.json").write_text('{"mqtt": {"host": "192.0.2.9"}}', encoding="utf-8")

    assert cli.main(["mqtt", "status"]) == 0
    out = capsys.readouterr().out
    assert "MQTT: aus" in out
    assert "192.0.2.9:1883" in out
    assert "fehlt" in out

    fake.values[("tapesmith", "mqtt")] = "pw"
    assert cli.main(["mqtt", "status"]) == 0
    out = capsys.readouterr().out
    assert "vorhanden" in out
    assert "pw" not in out
