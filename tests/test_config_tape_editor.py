"""Tests für die config.json-Schlüssel zu Band, Editor und Schneidpause (cut_pause_s, …)."""

import json

import pytest

from tapesmith import config, paths


def test_defaults_vorhanden():
    cfg = config.load_config()
    assert cfg["tape"]["current"] == "schwarz-weiss"
    assert config.tape_setting(cfg) == "schwarz-weiss"
    assert config.gui_setting(cfg, "editor_grid_dots") == 8
    assert config.gui_setting(cfg, "editor_snap") is True
    assert config.gui_setting(cfg, "screen_px_per_mm") is None
    assert config.gui_setting(cfg, "favorites") == []
    assert cfg["templates_dir"] is None
    assert cfg["cut_pause_s"] is None


def test_tape_setting_liest_wert(app_home):
    paths.config_path().write_text(json.dumps({"tape": {"current": "weiss-schwarz"}}), encoding="utf-8")
    cfg = config.load_config()
    assert config.tape_setting(cfg) == "weiss-schwarz"


def test_tape_muss_objekt_sein(app_home):
    paths.config_path().write_text(json.dumps({"tape": "schwarz-weiss"}), encoding="utf-8")
    with pytest.raises(ValueError, match="'tape' muss ein Objekt sein"):
        config.load_config()


def test_templates_dir_leerer_text_wirft(app_home):
    paths.config_path().write_text(json.dumps({"templates_dir": "  "}), encoding="utf-8")
    with pytest.raises(ValueError):
        config.load_config()


def test_templates_dir_none_ist_ok(app_home):
    paths.config_path().write_text(json.dumps({"templates_dir": None}), encoding="utf-8")
    config.load_config()


def test_templates_dir_text_ist_ok(app_home):
    paths.config_path().write_text(json.dumps({"templates_dir": "C:/vorlagen"}), encoding="utf-8")
    cfg = config.load_config()
    assert cfg["templates_dir"] == "C:/vorlagen"


@pytest.mark.parametrize("value", [-1, -0.5])
def test_cut_pause_s_negativ_wirft(app_home, value):
    paths.config_path().write_text(json.dumps({"cut_pause_s": value}), encoding="utf-8")
    with pytest.raises(ValueError):
        config.load_config()


@pytest.mark.parametrize("value", [None, 0, 2.5])
def test_cut_pause_s_gueltige_werte(app_home, value):
    paths.config_path().write_text(json.dumps({"cut_pause_s": value}), encoding="utf-8")
    cfg = config.load_config()
    assert cfg["cut_pause_s"] == value


def test_gui_screen_px_per_mm_0_wirft(app_home):
    paths.config_path().write_text(json.dumps({"gui": {"screen_px_per_mm": 0}}), encoding="utf-8")
    with pytest.raises(ValueError):
        config.load_config()


def test_gui_screen_px_per_mm_gueltig(app_home):
    paths.config_path().write_text(json.dumps({"gui": {"screen_px_per_mm": 10}}), encoding="utf-8")
    cfg = config.load_config()
    assert config.gui_setting(cfg, "screen_px_per_mm") == 10


def test_gui_editor_grid_dots_0_wirft(app_home):
    paths.config_path().write_text(json.dumps({"gui": {"editor_grid_dots": 0}}), encoding="utf-8")
    with pytest.raises(ValueError):
        config.load_config()


def test_gui_editor_grid_dots_zu_gross_wirft(app_home):
    paths.config_path().write_text(json.dumps({"gui": {"editor_grid_dots": 65}}), encoding="utf-8")
    with pytest.raises(ValueError):
        config.load_config()


def test_gui_favorites_muss_liste_von_texten_sein(app_home):
    paths.config_path().write_text(json.dumps({"gui": {"favorites": [1, 2]}}), encoding="utf-8")
    with pytest.raises(ValueError):
        config.load_config()


def test_gui_favorites_gueltig(app_home):
    paths.config_path().write_text(json.dumps({"gui": {"favorites": ["a", "b"]}}), encoding="utf-8")
    cfg = config.load_config()
    assert config.gui_setting(cfg, "favorites") == ["a", "b"]
