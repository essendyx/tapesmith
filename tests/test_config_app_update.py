"""Neue Konfigurationsschlüssel `app.language`, `app.theme` und Sektion `update`."""

import copy

import pytest

from tapesmith import config


def _cfg(**sections) -> dict:
    cfg = copy.deepcopy(config.DEFAULTS)
    cfg.update(sections)
    return cfg


def test_standardwerte_vorhanden():
    assert config.SECTION_DEFAULTS["app"] == {"language": "auto", "theme": "system"}
    assert config.SECTION_DEFAULTS["update"] == {
        "enabled": False, "asked": False, "source": "github:essendyx/tapesmith",
        "channel": "stable", "check_interval_h": 24, "auto_install": False, "idle_min": 10,
        "keep_versions": 2,
    }
    cfg = _cfg()
    assert config.setting(cfg, "app.language") == "auto"
    assert config.setting(cfg, "app.theme") == "system"
    assert config.setting(cfg, "update.source") == "github:essendyx/tapesmith"
    # Ohne Zustimmung keine automatische Verbindung zur Update-Quelle
    assert config.setting(cfg, "update.enabled") is False
    assert config.setting(cfg, "update.asked") is False
    config.validate_config(cfg)


@pytest.mark.parametrize("source", ["github:essendyx/tapesmith", "file:\\\\nas\\p12",
                                    "https://example.org/p12/", "http://nas.local/p12/"])
def test_gueltige_quellen(source):
    config.validate_config(_cfg(update={"source": source}))


@pytest.mark.parametrize("source", ["github:ohne-slash", "ftp://x", "https://a b", "file:", "file:   ",
                                    "https://x/#frag", "github:a/b/c", "", 5, None])
def test_ungueltige_quellen(source):
    with pytest.raises(ValueError, match=r"config.json: 'update.source' muss"):
        config.validate_config(_cfg(update={"source": source}))


@pytest.mark.parametrize("key, value, ok", [
    ("check_interval_h", 0, False), ("check_interval_h", 721, False), ("check_interval_h", 1, True),
    ("check_interval_h", 720, True), ("check_interval_h", 24.5, False), ("check_interval_h", True, False),
    ("idle_min", 0, False), ("idle_min", 1440, True), ("idle_min", 1441, False),
    ("keep_versions", 0, False), ("keep_versions", 5, True), ("keep_versions", 6, False),
    ("enabled", "ja", False), ("enabled", False, True), ("asked", True, True), ("asked", None, False),
    ("auto_install", 1, False), ("auto_install", True, True),
    ("channel", "beta", True), ("channel", "nightly", False),
])
def test_update_zahlen_und_schalter(key, value, ok):
    cfg = _cfg(update={key: value})
    if ok:
        config.validate_config(cfg)
    else:
        with pytest.raises(ValueError, match=rf"config.json: 'update.{key}' muss"):
            config.validate_config(cfg)


def test_alter_token_ref_wird_ignoriert():
    """GitHub braucht kein Token mehr: ein alter Eintrag `update.token_ref` bleibt gültig und wirkungslos."""
    config.validate_config(_cfg(update={"token_ref": None}))
    config.validate_config(_cfg(update={"token_ref": "quatsch:"}))
    assert "token_ref" not in config.SECTION_DEFAULTS["update"]
    with pytest.raises(KeyError):
        config.setting({}, "update.token_ref")


def test_sprache_und_farbschema():
    config.validate_config(_cfg(app={"language": "en", "theme": "dunkel"}))
    with pytest.raises(ValueError, match="config.json: 'app.language' muss"):
        config.validate_config(_cfg(app={"language": "fr"}))
    with pytest.raises(ValueError, match="config.json: 'app.theme' muss"):
        config.validate_config(_cfg(app={"theme": "dark"}))


def test_set_setting_kennt_die_neuen_schluessel(app_home):
    config.set_setting("update.channel", "beta")
    config.set_setting("app.language", "en")
    cfg = config.load_config()
    assert config.setting(cfg, "update.channel") == "beta"
    assert config.setting(cfg, "app.language") == "en"
    with pytest.raises(ValueError):
        config.set_setting("update.check_interval_h", 0)
