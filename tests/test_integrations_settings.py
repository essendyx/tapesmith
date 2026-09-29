"""Einstellungsdatei homelab.json."""

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from homelab_fakes import FakeKeyring, token_file, write_homelab
from tapesmith import paths
from tapesmith.integrations import settings

SRC = Path(__file__).resolve().parents[1] / "src"


def test_paths(app_home):
    assert settings.settings_path() == paths.app_dir() / "homelab.json"
    data_dir = settings.data_dir()
    assert data_dir == paths.app_dir() / "homelab"
    assert data_dir.is_dir()


def test_defaults_without_file():
    data = settings.load_settings()
    assert data == settings.DEFAULTS
    data["paperless"]["warranty_fields"]["kaufdatum"] = "X"
    data["obsidian"]["folders"].append("Neu")
    assert settings.DEFAULTS["paperless"]["warranty_fields"]["kaufdatum"] == "Kaufdatum"
    assert settings.DEFAULTS["obsidian"]["folders"] == ["Hosts", "Dienste"]


def test_file_overrides_are_merged_per_section():
    write_homelab({"paperless": {"asn_prefix": "PL"}})
    data = settings.load_settings()
    assert data["paperless"]["asn_prefix"] == "PL"
    assert data["paperless"]["url"] == settings.DEFAULTS["paperless"]["url"]


def test_nested_object_is_replaced_as_a_whole():
    fields = {"kaufdatum": "Gekauft", "garantie_monate": "Monate", "garantie_bis": "Bis"}
    write_homelab({"paperless": {"warranty_fields": fields}})
    assert settings.load_settings()["paperless"]["warranty_fields"] == fields


def test_setting_reads_value_and_unknown_is_key_error():
    data = settings.load_settings()
    assert settings.setting(data, "assets.prefix") == "HL-"
    with pytest.raises(KeyError):
        settings.setting(data, "assets.foo")
    with pytest.raises(KeyError):
        settings.setting(data, "nichts")


@pytest.mark.parametrize("key, value", [
    ("paperless.url", "ftp://x"),
    ("paperless.url", "http://x/"),
    ("assets.prefix", "hl-"),
    ("assets.width", 13),
    ("plausi.networks", []),
    ("proxmox.hosts", [{"name": "a", "url": "https://a:8006", "token_ref": "blub"}]),
    ("homeassistant.todo_entity", "calendar.x"),
    ("paperless.foo", "x"),
])
def test_validate_rejects_bad_values(key, value):
    data = copy.deepcopy(settings.DEFAULTS)
    section, _, name = key.partition(".")
    data[section][name] = value
    errors = settings.validate(data)
    assert len(errors) == 1, errors
    assert errors[0].startswith("homelab.json: ")
    target = "proxmox.hosts" if key == "proxmox.hosts" else key
    assert f"'{target}" in errors[0]


@pytest.mark.parametrize("key, value", [
    ("paperless.url", "https://paperless.example.com"),
    ("paperless.public_url", None),
    ("paperless.timeout_s", 30),
    ("assets.check_digit", True),
    ("assets.prefix", ""),
    ("homeassistant.todo_entity", "todo.einkauf"),
    ("homeassistant.battery_below", 20),
    ("obsidian.vault_dir", "D:\\Vault"),
    ("obsidian.folders", ["Hosts", "Dienste/Docker"]),
    ("plausi.networks", ["192.0.2.0/24", "10.0.0.1/8"]),
    ("proxmox.hosts", [{"name": "pmx10", "url": "https://192.0.2.60:8006",
                        "token_ref": "keyring:tapesmith/pmx10", "verify_tls": False}]),
    ("shortlink.base_url", "https://l.example.com"),
])
def test_validate_accepts_good_values(key, value):
    data = copy.deepcopy(settings.DEFAULTS)
    section, _, name = key.partition(".")
    data[section][name] = value
    assert settings.validate(data) == []


def test_validate_collects_all_errors_in_section_order():
    data = copy.deepcopy(settings.DEFAULTS)
    data["plausi"]["dns_check"] = "ja"
    data["paperless"]["asn_width"] = -1
    data["proxmox"]["hosts"] = [
        {"name": "a", "url": "https://a:8006", "token_ref": "env:A"},
        {"name": "a", "url": "http://b:8006", "token_ref": "env:B"},
    ]
    errors = settings.validate(data)
    assert len(errors) == 4
    assert "paperless.asn_width" in errors[0]
    assert "proxmox.hosts" in errors[1] and "proxmox.hosts" in errors[2]
    assert "plausi.dns_check" in errors[3]


def test_validate_unknown_section():
    data = copy.deepcopy(settings.DEFAULTS)
    data["telegram"] = {}
    assert settings.validate(data) == ["homelab.json: unbekannter Schlüssel 'telegram'"]


def test_set_setting_writes_only_differences_atomically():
    path = settings.settings_path()
    result = settings.set_setting("assets.prefix", "AS-")
    assert result["assets"]["prefix"] == "AS-"
    assert json.loads(path.read_text(encoding="utf-8")) == {"assets": {"prefix": "AS-"}}
    settings.set_setting("assets.prefix", "HL-")
    assert json.loads(path.read_text(encoding="utf-8")) == {}
    assert not list(path.parent.glob("homelab.json.*.tmp"))


def test_set_setting_replaces_list():
    hosts = [{"name": "pmx10", "url": "https://192.0.2.60:8006", "token_ref": "env:PMX10",
              "verify_tls": False}]
    settings.set_setting("proxmox.hosts", hosts)
    settings.set_setting("proxmox.hosts", hosts[:0])
    assert settings.load_settings()["proxmox"]["hosts"] == []


def test_set_setting_invalid_raises_and_keeps_file():
    path = write_homelab({"assets": {"prefix": "AS-"}})
    before = path.read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="assets.width"):
        settings.set_setting("assets.width", 99)
    with pytest.raises(ValueError, match="unbekannter Schlüssel"):
        settings.set_setting("assets.foo", 1)
    assert path.read_text(encoding="utf-8") == before


def test_update_settings_applies_all_or_nothing():
    path = settings.settings_path()
    with pytest.raises(ValueError):
        settings.update_settings({"assets.prefix": "AS-", "assets.width": 99})
    assert not path.exists()
    data = settings.update_settings({"assets.prefix": "AS-", "kabel.width": 4})
    assert data["kabel"]["width"] == 4
    assert json.loads(path.read_text(encoding="utf-8")) == {"assets": {"prefix": "AS-"},
                                                           "kabel": {"width": 4}}


def test_public_view_never_contains_secret(tmp_path):
    ref = token_file(tmp_path, "paperless", "geheim-123")
    data = copy.deepcopy(settings.DEFAULTS)
    data["paperless"]["token_ref"] = ref
    data["shortlink"]["token_ref"] = f"file:{tmp_path / 'fehlt'}"
    data["homeassistant"]["token_ref"] = "keyring:tapesmith/ha"
    data["proxmox"]["hosts"] = [{"name": "pmx10", "url": "https://192.0.2.60:8006",
                                 "token_ref": token_file(tmp_path, "pve", "geheim-456")}]
    view = settings.public_view(data, keyring_module=FakeKeyring())
    text = json.dumps(view)
    assert "geheim-123" not in text and "geheim-456" not in text
    assert view["paperless"]["token_set"] is True
    assert view["paperless"]["token_describe"].startswith("Datei ")
    assert view["shortlink"]["token_set"] is False
    assert view["homeassistant"]["token_set"] is False
    assert view["homeassistant"]["token_describe"] == "Windows-Anmeldeinformationen tapesmith/ha"
    host = view["proxmox"]["hosts"][0]
    assert host["token_set"] is True and host["token_describe"].startswith("Datei ")
    assert "token_set" not in data["paperless"]


def test_broken_json_raises_value_error():
    settings.settings_path().write_text("{kaputt", encoding="utf-8")
    with pytest.raises(ValueError, match="homelab.json"):
        settings.load_settings()


def test_invalid_file_lists_all_errors():
    write_homelab({"assets": {"width": 99}, "kabel": {"prefix": "k"}})
    with pytest.raises(ValueError) as info:
        settings.load_settings()
    assert "assets.width" in str(info.value) and "kabel.prefix" in str(info.value)
    assert "; " in str(info.value)


def test_check_services_without_network(tmp_path):
    data = copy.deepcopy(settings.DEFAULTS)
    data["paperless"]["token_ref"] = token_file(tmp_path, "p")
    data["shortlink"]["token_ref"] = f"file:{tmp_path / 'x'}"
    data["homeassistant"]["token_ref"] = f"file:{tmp_path / 'y'}"
    services = settings.check_services(data)
    ids = [s["id"] for s in services]
    assert ids == ["paperless", "proxmox", "obsidian", "homeassistant", "shortlink"]
    by_id = {s["id"]: s for s in services}
    assert by_id["paperless"]["token_set"] is True
    assert by_id["proxmox"]["configured"] is False
    assert by_id["proxmox"]["detail"] == "Keine Proxmox-Hosts eingetragen"
    assert by_id["obsidian"]["token_set"] is None
    assert by_id["shortlink"]["configured"] is False


def test_integrations_qt_free():
    code = ("import tapesmith.integrations.settings, tapesmith.integrations.credentials, "
            "tapesmith.integrations.errors, tapesmith.integrations.httpclient, "
            "tapesmith.integrations.scancache, tapesmith.integrations.shortlink, "
            "tapesmith.integrations.cliprint, tapesmith.webapi.routes_homelab, "
            "tapesmith.webapi.homelab_common; import sys; "
            "assert 'PySide6' not in sys.modules, 'PySide6 geladen'")
    env = {**__import__("os").environ, "PYTHONPATH": str(SRC)}
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env,
                            timeout=120)
    assert result.returncode == 0, result.stderr


def test_check_obsidian_mit_lokalem_vault_ordner_gilt_als_eingerichtet(tmp_path):
    data = copy.deepcopy(settings.DEFAULTS)
    by_id = {s["id"]: s for s in settings.check_services(data)}
    assert by_id["obsidian"]["configured"] is False
    data["obsidian"]["vault_dir"] = str(tmp_path)
    by_id = {s["id"]: s for s in settings.check_services(data)}
    assert by_id["obsidian"]["configured"] is True
    assert str(tmp_path) in by_id["obsidian"]["detail"]
