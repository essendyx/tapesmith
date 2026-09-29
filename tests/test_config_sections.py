"""Tests für die sektionierten Konfigurationsschlüssel (Dienst, Warteschlange, Tray und mehr)."""

import json

import pytest

from tapesmith import config, paths


def test_setting_liefert_defaults_und_werte():
    assert config.setting({}, "queue.backoff_start_s") == 30
    assert config.setting({"queue": {"backoff_start_s": 45}}, "queue.backoff_start_s") == 45
    cfg = config.load_config()
    assert config.setting(cfg, "idle_timeout_s") == 300
    assert config.setting(cfg, "gui.editor_snap") is True
    with pytest.raises(KeyError):
        config.setting({}, "unbekannt.schluessel")
    with pytest.raises(KeyError):
        config.setting({}, "unbekannt")


def test_load_config_validiert_neue_sektionen():
    path = paths.config_path()

    path.write_text(json.dumps({"queue": {"probe": "xyz"}}), encoding="utf-8")
    with pytest.raises(ValueError, match="queue.probe"):
        config.load_config()

    path.write_text(json.dumps({"queue": {"backoff_start_s": 100, "backoff_max_s": 10}}), encoding="utf-8")
    with pytest.raises(ValueError, match="backoff_max_s"):
        config.load_config()

    path.write_text(json.dumps({"tray": {"toast_s": 20}}), encoding="utf-8")
    with pytest.raises(ValueError, match="tray.toast_s"):
        config.load_config()

    path.write_text(json.dumps({"ssh": {"hosts": [
        {"name": "pmx10", "host": "-oProxyCommand=calc", "key": "~/.ssh/id"}
    ]}}), encoding="utf-8")
    with pytest.raises(ValueError, match="ssh.hosts"):
        config.load_config()

    path.write_text(json.dumps({"ssh": {"hosts": [
        {"name": "a", "host": "h1", "key": "k"},
        {"name": "a", "host": "h2", "key": "k"},
    ]}}), encoding="utf-8")
    with pytest.raises(ValueError, match="doppelter Name"):
        config.load_config()

    path.write_text(json.dumps({"ssh": {"hosts": [
        {"name": "a", "host": "h1", "user": "Root Admin", "key": "k"},
    ]}}), encoding="utf-8")
    with pytest.raises(ValueError, match="ssh.hosts"):
        config.load_config()

    path.write_text(json.dumps({"ble": {"address": "xyz"}}), encoding="utf-8")
    with pytest.raises(ValueError, match="ble.address"):
        config.load_config()

    # Gültige Konfiguration mit allen Sektionen lädt.
    full = {
        "daemon": {"enabled": True, "spawn": False, "connect_timeout_s": 3.0,
                   "start_timeout_s": 5.0, "idle_exit_s": 0},
        "queue": {"enabled": True, "auto_retry": False, "backoff_start_s": 10,
                  "backoff_max_s": 60, "probe": "ble", "cli_default": True},
        "status": {"poll_s": 30},
        "hotkey": {"enabled": True, "quick": "Ctrl+Alt+L", "clipboard": "Ctrl+Alt+Shift+L"},
        "tray": {"favorites": [{"title": "A", "template": "b", "values": {"x": "y"}}],
                 "toast_s": 5, "notify": False},
        "ble": {"address": "00:11:22:33:44:55", "names": ["P12"], "scan_timeout_s": 5.0},
        "ssh": {"hosts": [{"name": "pmx10", "host": "192.0.2.60", "key": "~/.ssh/id"}],
                "timeout_s": 15, "strict_host_key": True},
        "archive": {"dir": None, "git_commit": False},
        "backup": {"dir": None, "keep": 5, "auto_daily": True},
        "numbering": {"dir": None},
    }
    path.write_text(json.dumps(full), encoding="utf-8")
    cfg = config.load_config()
    assert cfg["queue"]["probe"] == "ble"
    assert cfg["ble"]["address"] == "001122334455"


def test_unbekannter_schluessel_in_sektion_kein_fehler():
    path = paths.config_path()
    path.write_text(json.dumps({"queue": {"neu": 1}}), encoding="utf-8")
    cfg = config.load_config()
    assert cfg["queue"]["neu"] == 1


def test_set_setting_schreibt_sektion_und_behaelt_andere_schluessel():
    config.save_config({"queue": {"enabled": False}})
    result = config.set_setting("queue.backoff_start_s", 60)
    assert result["queue"]["backoff_start_s"] == 60
    assert result["queue"]["enabled"] is False

    with pytest.raises(ValueError):
        config.set_setting("queue.probe", "xyz")
    data = json.loads(paths.config_path().read_text(encoding="utf-8"))
    assert data["queue"]["backoff_start_s"] == 60
    assert "probe" not in data["queue"]


@pytest.mark.parametrize("text,expected", [
    ("true", True),
    ("30", 30),
    ("2.5", 2.5),
    ("null", None),
    ('["a"]', ["a"]),
    ("Ctrl+Alt+L", "Ctrl+Alt+L"),
])
def test_parse_cli_value(text, expected):
    assert config.parse_cli_value(text) == expected


def test_secret_keys():
    cfg = {"x": {"api_token": "abc"}, "y": {"password": "keyring:p12/y"}}
    assert config.secret_keys(cfg) == ["x.api_token"]
