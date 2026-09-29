"""Modulregister (`tapesmith.modules`): Beschreibung, Schalter in config.json, Zuordnung von Routen,
CLI-Befehlen und Vorlagen, Fehlercode `module.disabled` und die abgeleitete Web-Beschreibung."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tapesmith import config, i18n, modules, paths
from tapesmith.errors import CODE_STATUS, ERROR_CODES, error_code, explain

ROOT = Path(__file__).resolve().parent.parent
WEB_REGISTRY = ROOT / "web" / "src" / "modules" / "registry.json"

EXPECTED_IDS = ("inventar", "datentraeger", "proxmox", "paperless", "homeassistant", "vault", "assets",
                "kabel", "kleinanzeigen", "snscan")


def test_modulliste_fest():
    assert modules.MODULE_IDS == EXPECTED_IDS
    assert [spec.id for spec in modules.REGISTRY] == list(EXPECTED_IDS)


def test_jedes_modul_vollstaendig_beschrieben():
    for spec in modules.REGISTRY:
        assert spec.kind in ("werkzeug", "integration")
        assert spec.pages, spec.id
        assert spec.nav.startswith(("sidebar:", "homelab:")), spec.id
        assert spec.api, spec.id
        for lang in ("de", "en"):
            texts = modules.texts(spec.id, lang)
            for key in ("name", "description", "example"):
                assert texts[key].strip(), (spec.id, lang, key)
            assert texts["description"].rstrip().endswith("."), (spec.id, lang)
            assert texts["example"].startswith(("Beispiel:", "Example:")), (spec.id, lang)


def test_standard_aus_ohne_daten(real_module_detection):
    cfg = config.load_config()
    assert modules.enabled_ids(cfg) == ()
    assert config.SECTION_DEFAULTS["modules"] == {"enabled": []}


def test_explizite_liste_gilt_und_unbekannte_werden_ignoriert():
    cfg = {"modules": {"enabled": ["proxmox", "gibtesnicht", "inventar"]}}
    # Reihenfolge immer wie im Register
    assert modules.enabled_ids(cfg) == ("inventar", "proxmox")
    assert modules.is_enabled(cfg, "proxmox")
    assert not modules.is_enabled(cfg, "vault")


def test_config_prueft_modulliste():
    with pytest.raises(ValueError, match="modules.enabled"):
        config.validate_config({**config.DEFAULTS, "modules": {"enabled": "proxmox"}})
    with pytest.raises(ValueError, match="modules.enabled"):
        config.validate_config({**config.DEFAULTS, "modules": {"enabled": [1]}})
    config.validate_config({**config.DEFAULTS, "modules": {"enabled": ["proxmox", "kuenftig"]}})


def test_ein_und_ausschalten_speichert_in_config(real_module_detection):
    modules.set_enabled("vault", True)
    assert json.loads(paths.config_path().read_text(encoding="utf-8"))["modules"]["enabled"] == ["vault"]
    modules.set_enabled("inventar", True)
    modules.set_enabled("vault", False)
    assert modules.enabled_ids(config.load_config()) == ("inventar",)
    with pytest.raises(modules.UnknownModule):
        modules.set_enabled("gibtesnicht", True)


def test_ohne_schluessel_gilt_die_erkennung_danach_die_liste(real_module_detection):
    # Ältere config.json ohne "modules": Module mit vorhandenen Daten gelten als eingeschaltet.
    homelab = paths.app_dir() / "homelab.json"
    homelab.write_text(json.dumps({"proxmox": {"hosts": [{"name": "pve", "url": "https://192.0.2.5:8006",
                                                          "token_ref": "env:PVE"}]}}), encoding="utf-8")
    # Der Seriennummer-Scan gehört zu den Homelab-Werkzeugen und kommt mit.
    assert modules.enabled_ids(config.load_config()) == ("proxmox", "snscan")
    # Sobald die Liste gespeichert ist, gilt nur noch sie.
    modules.set_enabled("proxmox", False)
    assert modules.enabled_ids(config.load_config()) == ("snscan",)


@pytest.mark.parametrize("path, expected", [
    ("/api/v1/inventory/boxes", ("inventar",)),
    ("/api/v1/inventory/boxes/{box_id}", ("inventar",)),
    ("/api/v1/drives", ("datentraeger",)),
    ("/api/v1/ssh/scan", ("datentraeger",)),
    ("/api/v1/homelab/zfs/plan", ("datentraeger",)),
    ("/api/v1/homelab/proxmox/guests", ("proxmox",)),
    ("/api/v1/homelab/paperless/asn/next", ("paperless",)),
    ("/api/v1/homelab/ha/batteries", ("homeassistant",)),
    ("/api/v1/homelab/vault/notes", ("vault",)),
    ("/api/v1/homelab/assets", ("assets",)),
    ("/api/v1/homelab/assets/{asset_id}/vault-note", ("vault", "assets")),
    ("/api/v1/homelab/kabel/ids", ("kabel",)),
    ("/api/v1/homelab/ka", ("kleinanzeigen",)),
    ("/api/v1/homelab/ka/{ka_id}/label", ("kleinanzeigen",)),
    ("/api/v1/homelab/codescan", ("snscan",)),
    ("/api/v1/homelab/settings", ()),
    ("/api/v1/homelab/check", ()),
    ("/api/v1/homelab/plausi", ()),
    ("/api/v1/templates", ()),
    ("/api/v1/modules", ()),
])
def test_api_pfade_zu_modulen(path, expected):
    assert set(modules.modules_for_api(path)) == set(expected)


def test_cli_befehle_zu_modulen():
    mapping = {cmd: spec.id for spec in modules.REGISTRY for cmd in spec.cli}
    assert mapping == {
        "inv": "inventar", "drives": "datentraeger", "disks": "datentraeger", "platte": "datentraeger",
        "proxmox": "proxmox", "asn": "paperless", "garantie": "paperless", "batterie": "homeassistant",
        "vault": "vault", "asset-notiz": "vault", "asset": "assets", "kurz": "assets", "kabel": "kabel",
        "ka": "kleinanzeigen", "sn-scan": "snscan",
    }


def test_modulvorlagen_ausblenden():
    cfg = {"modules": {"enabled": ["proxmox"]}}
    hidden = modules.hidden_templates(cfg)
    assert "vm-lxc" not in hidden
    for name in ("asn", "garantie", "garantie-qr", "datentraeger", "datentraeger-qr", "platte-defekt",
                 "aufbewahrungsbox", "batterie", "asset-tag", "asset-kurz", "ka-artikel"):
        assert name in hidden
    # allgemeine Vorlagen gehören keinem Modul
    for name in ("gefriergut", "kabelfahne", "host-ip", "wartung"):
        assert modules.module_of_template(name) is None
    assert modules.hidden_templates({"modules": {"enabled": list(EXPECTED_IDS)}}) == frozenset()


def test_modulvorlagen_gibt_es_wirklich():
    from tapesmith.templates.store import list_templates

    names = {t.name for t in list_templates()}
    for spec in modules.REGISTRY:
        for name in spec.templates:
            assert name in names, (spec.id, name)


def test_fehlercode_module_disabled():
    assert "module.disabled" in ERROR_CODES
    assert CODE_STATUS["module.disabled"] == 409
    exc = modules.ModuleDisabled("proxmox")
    assert error_code(exc) == "module.disabled"
    assert exc.http_status == 409
    text = str(exc)
    assert "Modul Proxmox ist ausgeschaltet" in text
    assert "Einstellungen > Module" in text
    assert "tapesmith module enable proxmox" in text
    assert explain(exc).title == i18n.tr("errors.module.disabled.title", "de")


def test_web_beschreibung_ist_aus_dem_register_abgeleitet():
    """`web/src/modules/registry.json` entsteht aus dem Python-Register
    (`python -m tapesmith.modules --write-web`) und muss aktuell sein."""
    assert json.loads(WEB_REGISTRY.read_text(encoding="utf-8")) == modules.registry_json()
    assert WEB_REGISTRY.read_text(encoding="utf-8") == modules.registry_json_text()


def test_registry_json_felder():
    data = modules.registry_json()
    entry = next(m for m in data["modules"] if m["id"] == "paperless")
    assert entry["pages"] == ["/homelab/paperless"]
    assert entry["nav"] == {"area": "homelab", "key": "paperless"}
    assert entry["cli"] == ["asn", "garantie"]
    assert entry["templates"] == ["asn", "garantie", "garantie-qr"]
    assert entry["settings"] == ["homelab:paperless"]
    assert entry["integrations"] == ["paperless"]
    assert entry["setup"] is True
    assert [m["id"] for m in data["modules"] if m["setup"]] == ["proxmox", "paperless", "homeassistant", "vault"]
    assert entry["texts"]["de"]["name"] == "Paperless"
    assert entry["texts"]["en"]["description"].startswith("Assigns ASN numbers")
