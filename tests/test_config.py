import json

import pytest

from tapesmith import config, paths


def test_defaults_include_new_timeouts():
    assert config.DEFAULTS["idle_timeout_s"] == 300
    assert config.DEFAULTS["connect_timeout_s"] == 5


def test_load_config_defaults_when_no_file():
    cfg = config.load_config()
    assert cfg["idle_timeout_s"] == 300
    assert cfg["connect_timeout_s"] == 5
    assert cfg["mac"] is None


def test_save_config_normalizes_mac_and_keeps_unknown_keys(app_home):
    path = paths.config_path()
    path.write_text(json.dumps({"x": 1}), encoding="utf-8")

    result = config.save_config({"mac": "00:11:22:33:44:55"})

    assert result["mac"] == "001122334455"
    assert result["x"] == 1
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["mac"] == "001122334455"
    assert on_disk["x"] == 1
    assert list(path.parent.glob("*.tmp")) == []


def test_save_config_without_existing_file(app_home):
    result = config.save_config({"transport": "COM9"})
    assert result == {"transport": "COM9"}
    assert json.loads(paths.config_path().read_text(encoding="utf-8")) == {"transport": "COM9"}


def test_connect_timeout_zero_raises_value_error_mentioning_config_json(app_home):
    paths.config_path().write_text(json.dumps({"connect_timeout_s": 0}), encoding="utf-8")
    with pytest.raises(ValueError, match="config.json"):
        config.load_config()


def test_idle_timeout_negative_raises_value_error(app_home):
    paths.config_path().write_text(json.dumps({"idle_timeout_s": -1}), encoding="utf-8")
    with pytest.raises(ValueError, match="config.json"):
        config.load_config()
