"""Tests für die Sektionen `lan`, `family`, `mcp`, `hotfolder`, `mqtt`, `telegram`."""

import pytest

from tapesmith import config


def test_setting_liefert_lan_automation_defaults():
    assert config.setting({}, "lan.enabled") is False
    assert config.setting({}, "lan.allowed_networks") == ["192.168.0.0/16"]
    assert config.setting({}, "family.templates")[0] == "gefriergut"
    assert config.setting({}, "family.freetext_enabled") is True
    assert config.setting({}, "mqtt.host") is None
    assert config.setting({}, "telegram.quiet_hours") == "22:00-07:00"


@pytest.mark.parametrize("section, key, value", [
    ("lan", "bind", "127.0.0.1"),
    ("lan", "bind", "abc"),
    ("lan", "allowed_networks", []),
    ("lan", "allowed_networks", ["0.0.0.0/0"]),
    ("lan", "allowed_networks", ["8.8.8.0/24"]),
    ("lan", "allowed_networks", ["10.0.0.0/4"]),
    ("lan", "allowed_networks", ["192.0.2.0/24", 5]),
    ("lan", "public_url", "ftp://x"),
    ("family", "max_copies", 0),
    ("family", "max_copies", 21),
    ("family", "templates", ["Gefrier Gut"]),
    ("family", "freetext_enabled", "true"),
    ("hotfolder", "poll_s", 0.1),
    ("mqtt", "port", 70000),
    ("mqtt", "base_topic", "p12/#"),
    ("mqtt", "password_ref", "geheim123"),
    ("telegram", "chat_id", True),
    ("telegram", "chat_id", "abc"),
    ("telegram", "quiet_hours", "25:00-07:00"),
    ("telegram", "quiet_hours", "07:00-07:00"),
    ("telegram", "roll_low_m", -1),
])
def test_validate_config_lan_automation_ungueltig(section, key, value):
    cfg = config.load_config()
    cfg[section] = {key: value}
    with pytest.raises(ValueError):
        config.validate_config(cfg)


@pytest.mark.parametrize("section, key, value", [
    ("lan", "bind", "192.0.2.50"),
    ("lan", "allowed_networks", ["192.0.2.0/24", "10.8.0.0/16"]),
    ("telegram", "chat_id", -1001234567890),
    ("telegram", "chat_id", "-1001234567890"),
    ("telegram", "chat_id", "@mein_kanal"),
    ("telegram", "quiet_hours", None),
])
def test_validate_config_lan_automation_gueltig(section, key, value):
    cfg = config.load_config()
    cfg[section] = {key: value}
    config.validate_config(cfg)


def test_set_setting_lan_enabled_speichert_ganze_sektion():
    calls = []
    config.set_setting("lan.enabled", True, save=calls.append)
    assert calls == [{"lan": {"enabled": True}}]


def test_set_setting_lan_bind_ungueltig_speichert_nicht():
    calls = []
    with pytest.raises(ValueError):
        config.set_setting("lan.bind", "abc", save=calls.append)
    assert calls == []


def test_secret_keys_erkennt_referenzen():
    cfg = {
        "mqtt": {"password_ref": "keyring:tapesmith/mqtt"},
        "telegram": {"token_ref": "file:C:/x"},
        "x": {"token": "klartext"},
    }
    assert config.secret_keys(cfg) == ["x.token"]
