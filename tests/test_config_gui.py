"""Tests für die GUI-Einstellungen in config.py: DEFAULTS["gui"], gui_setting,
Validierung von 'gui' als Objekt."""

import json

import pytest

from tapesmith import config, paths


def test_load_config_without_file_has_empty_gui_and_defaults():
    cfg = config.load_config()
    assert cfg["gui"] == {}
    assert config.gui_setting(cfg, "ctrl_enter_only") is False
    assert config.gui_setting(cfg, "preview_mode") == "design"


def test_gui_setting_unknown_key_raises_key_error():
    cfg = config.load_config()
    with pytest.raises(KeyError):
        config.gui_setting(cfg, "x")


def test_load_config_with_gui_object_overrides_default(app_home):
    paths.config_path().write_text(
        json.dumps({"gui": {"ctrl_enter_only": True}}), encoding="utf-8")
    cfg = config.load_config()
    assert config.gui_setting(cfg, "ctrl_enter_only") is True
    assert config.gui_setting(cfg, "preview_mode") == "design"


def test_load_config_with_non_object_gui_raises_value_error(app_home):
    paths.config_path().write_text(json.dumps({"gui": 5}), encoding="utf-8")
    with pytest.raises(ValueError, match="'gui' muss ein Objekt sein"):
        config.load_config()
