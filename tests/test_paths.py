import json
import pytest

from tapesmith import config, paths


def test_app_dir_uses_env_and_is_created(app_home):
    assert paths.app_dir() == app_home
    assert app_home.is_dir()


def test_file_paths_live_in_app_dir(app_home):
    assert paths.calibration_path() == app_home / "calibration.json"
    assert paths.capabilities_path() == app_home / "capabilities.json"
    assert paths.config_path() == app_home / "config.json"
    assert paths.log_dir() == app_home / "logs"
    assert paths.log_dir().is_dir()


def test_history_db_path_lives_in_app_dir(app_home):
    assert paths.history_db_path() == app_home / "history.sqlite3"


def test_config_defaults_without_file():
    cfg = config.load_config()
    assert cfg == {
        "mac": None,
        "transport": "auto",
        "idle_timeout_s": 300,
        "connect_timeout_s": 5,
        "guard": {},
        "gui": {},
        "tape": {"current": "schwarz-weiss"},
        "templates_dir": None,
        "cut_pause_s": None,
    }


def test_config_file_overrides_and_normalizes_mac(app_home):
    paths.config_path().write_text(json.dumps({"mac": "a4:5f:98:1a:35:46"}), encoding="utf-8")
    cfg = config.load_config()
    assert cfg["mac"] == "A45F981A3546"
    assert cfg["transport"] == "auto"


def test_invalid_mac_is_rejected(app_home):
    paths.config_path().write_text(json.dumps({"mac": "not-a-mac"}), encoding="utf-8")
    with pytest.raises(ValueError, match="MAC"):
        config.load_config()


# Harte Sperre gegen echte Nutzerdaten unter pytest

def test_app_dir_ohne_home_unter_pytest_wirft(monkeypatch, tmp_path):
    fake_appdata = tmp_path / "appdata"
    monkeypatch.delenv("TAPESMITH_HOME", raising=False)
    monkeypatch.setenv("APPDATA", str(fake_appdata))
    with pytest.raises(RuntimeError, match="TAPESMITH_HOME"):
        paths.app_dir()
    assert not (fake_appdata / "Tapesmith").exists()


def test_app_dir_leeres_home_unter_pytest_wirft(monkeypatch, tmp_path):
    monkeypatch.setenv("TAPESMITH_HOME", "")
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    with pytest.raises(RuntimeError, match="TAPESMITH_HOME"):
        paths.app_dir()


def test_app_dir_sperre_auch_ohne_pytest_current_test(monkeypatch, tmp_path):
    # Modul pytest geladen reicht (z. B. Import-Zeit, Sammelphase, Fixtures)
    monkeypatch.delenv("TAPESMITH_HOME", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    with pytest.raises(RuntimeError, match="TAPESMITH_HOME"):
        paths.app_dir()


def test_app_dir_ausserhalb_pytest_nutzt_appdata(tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path

    fake_appdata = tmp_path / "appdata"
    env = {k: v for k, v in os.environ.items() if k not in ("TAPESMITH_HOME", "PYTEST_CURRENT_TEST")}
    env["APPDATA"] = str(fake_appdata)
    env["PYTHONPATH"] = str(Path(paths.__file__).resolve().parents[1])
    out = subprocess.run([sys.executable, "-c", "from tapesmith import paths; print(paths.app_dir())"],
                         env=env, capture_output=True, text=True, check=True)
    assert Path(out.stdout.strip()) == fake_appdata / "Tapesmith"
