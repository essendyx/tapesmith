"""Tests für die Sektionen `web`/`app`, `set_setting` ohne Punkt,
`UnknownSetting` und `check_transport`."""

import pytest

from tapesmith import config


def test_setting_liefert_web_und_app_defaults():
    assert config.setting({}, "web.port") == 8712
    assert "enabled" not in config.SECTION_DEFAULTS["web"]
    assert config.setting({}, "app.language") == "auto"


def test_app_quick_window_gibt_es_nicht_mehr():
    """Nur Browser plus Tray: kein Schalter mehr zwischen Web-Kompaktfenster und Qt-Popup."""
    with pytest.raises(KeyError):
        config.setting({}, "app.quick_window")
    with pytest.raises(config.UnknownSetting):
        config.set_setting("app.quick_window", "native", save=lambda cfg: None)


@pytest.mark.parametrize("port", [0, 80, 1023, 70000, "8712", True])
def test_validate_config_web_port_ungueltig(port):
    cfg = config.load_config()
    cfg["web"] = {"port": port}
    with pytest.raises(ValueError, match="web.port"):
        config.validate_config(cfg)


@pytest.mark.parametrize("port", [1024, 8712, 65535])
def test_validate_config_web_port_gueltig(port):
    cfg = config.load_config()
    cfg["web"] = {"port": port}
    config.validate_config(cfg)


@pytest.mark.parametrize("value", ["web", "native", "popup"])
def test_validate_config_alter_quick_window_eintrag_wird_ignoriert(value):
    """Eine config.json aus 0.2 mit `app.quick_window` bleibt gültig (der Eintrag wirkt nicht mehr)."""
    cfg = config.load_config()
    cfg["app"] = {"quick_window": value, "language": "de"}
    config.validate_config(cfg)


def test_set_setting_web_port_ungueltig_speichert_nicht():
    calls = []
    with pytest.raises(ValueError):
        config.set_setting("web.port", 80, save=calls.append)
    assert calls == []


def test_set_setting_transport_ohne_punkt():
    calls = []
    config.set_setting("transport", "com4", save=calls.append)
    assert calls == [{"transport": "COM4"}]

    calls.clear()
    config.set_setting("transport", "file:C:/tmp/j.bin", save=calls.append)
    assert calls == [{"transport": "file:C:/tmp/j.bin"}]

    for bad in ("COMX", ""):
        calls.clear()
        with pytest.raises(ValueError, match="Transport"):
            config.set_setting("transport", bad, save=calls.append)
        assert calls == []


def test_set_setting_mac_ohne_punkt_normalisiert():
    calls = []
    config.set_setting("mac", "00:11:22:33:44:55", save=calls.append)
    assert calls == [{"mac": "001122334455"}]


def test_set_setting_sektion_ohne_punkt_wirft_unknown_setting():
    with pytest.raises(config.UnknownSetting) as excinfo:
        config.set_setting("gui", True)
    assert str(excinfo.value).startswith("'gui' ist eine Sektion")
    assert "gui.ctrl_enter_only" in str(excinfo.value)


def test_set_setting_unbekannter_schluessel_ohne_punkt():
    with pytest.raises(config.UnknownSetting) as excinfo:
        config.set_setting("foo", 1)
    text = str(excinfo.value)
    assert "Unbekannter Schlüssel 'foo'" in text
    assert "transport" in text


def test_set_setting_unbekannter_schluessel_mit_punkt():
    with pytest.raises(config.UnknownSetting):
        config.set_setting("queue.gibtsnicht", 1)


def test_set_setting_guard_tape_web_mit_punkt_ok():
    calls = []
    config.set_setting("guard.max_copies", 20, save=calls.append)
    assert calls == [{"guard": {"max_copies": 20}}]

    calls.clear()
    config.set_setting("tape.current", "weiss-schwarz", save=calls.append)
    assert calls == [{"tape": {"current": "weiss-schwarz"}}]

    calls.clear()
    config.set_setting("web.port", 9000, save=calls.append)
    assert calls == [{"web": {"port": 9000}}]


def test_check_transport_normalisiert_und_prueft():
    assert config.check_transport("com4") == "COM4"
    assert config.check_transport("COM12") == "COM12"
    assert config.check_transport("auto") == "auto"
    assert config.check_transport("ble") == "ble"
    assert config.check_transport("ble:001122334455") == "ble:001122334455"
    assert config.check_transport("usb") == "usb"
    assert config.check_transport("file:C:/x/job.bin") == "file:C:/x/job.bin"
    for bad in ("comx", "", "ble:", "file:", "quatsch"):
        with pytest.raises(ValueError, match="Transport"):
            config.check_transport(bad)


def test_alter_schluessel_web_enabled_bleibt_gueltig_und_wird_ignoriert(app_home):
    (app_home).mkdir(parents=True, exist_ok=True)
    (app_home / "config.json").write_text('{"web": {"enabled": false, "port": 9001}}', encoding="utf-8")
    cfg = config.load_config()
    assert config.setting(cfg, "web.port") == 9001
    from tapesmith.webapi.server import web_settings
    assert web_settings(cfg, env={}) == 9001
