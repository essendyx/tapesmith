"""`tapesmith module list|enable|disable` und die Sperre der CLI-Befehle ausgeschalteter Module."""

from __future__ import annotations

import json

import pytest

from tapesmith import cli, config, modules, paths


def _write_modules(enabled: list[str]) -> None:
    config.save_config({"modules": {"enabled": enabled}})


def test_list_zeigt_alle_module_mit_zustand(capsys):
    _write_modules(["inventar"])
    assert cli.main(["module", "list"]) == 0
    out = capsys.readouterr().out
    lines = [line for line in out.splitlines() if line.strip()]
    assert any(line.startswith("[x] inventar") and "Inventar" in line for line in lines)
    assert any(line.startswith("[ ] proxmox") for line in lines)
    for module_id in modules.MODULE_IDS:
        assert module_id in out
    assert "Behalte den Überblick über Boxen" in out


def test_list_json(capsys):
    _write_modules(["vault"])
    assert cli.main(["module", "list", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert [m["id"] for m in data] == list(modules.MODULE_IDS)
    assert {m["id"]: m["enabled"] for m in data}["vault"] is True
    assert data[0]["name"] == "Inventar"


def test_enable_und_disable(capsys):
    _write_modules([])
    assert cli.main(["module", "enable", "proxmox", "vault"]) == 0
    assert "eingeschaltet: Proxmox, Obsidian-Vault" in capsys.readouterr().out
    stored = json.loads(paths.config_path().read_text(encoding="utf-8"))["modules"]["enabled"]
    assert stored == ["proxmox", "vault"]
    assert cli.main(["module", "disable", "vault"]) == 0
    assert "ausgeschaltet: Obsidian-Vault" in capsys.readouterr().out
    assert modules.enabled_ids(config.load_config()) == ("proxmox",)


def test_enable_all(capsys):
    _write_modules([])
    assert cli.main(["module", "enable", "--all"]) == 0
    assert modules.enabled_ids(config.load_config()) == modules.MODULE_IDS


def test_unbekanntes_modul(capsys):
    _write_modules([])
    assert cli.main(["module", "enable", "gibtesnicht"]) == 1
    err = capsys.readouterr().err
    assert "Unbekanntes Modul 'gibtesnicht'" in err
    assert "inventar" in err


@pytest.mark.parametrize("argv, module_id, name", [
    (["inv", "box", "list"], "inventar", "Inventar"),
    (["proxmox", "hosts"], "proxmox", "Proxmox"),
    (["asn", "next"], "paperless", "Paperless"),
    (["ka", "list"], "kleinanzeigen", "Kleinanzeigen"),
    (["kabel", "register"], "kabel", "Kabel"),
    (["drives"], "datentraeger", "Datenträger"),
])
def test_befehl_ausgeschaltetes_modul_meldet_klartext(capsys, argv, module_id, name):
    _write_modules([])
    assert cli.main(argv) == 1
    err = capsys.readouterr().err
    assert f"Modul {name} ist ausgeschaltet" in err
    assert "einschalten unter Einstellungen > Module" in err
    assert f"`tapesmith module enable {module_id}`" in err


def test_kernbefehle_bleiben(capsys):
    _write_modules([])
    assert cli.main(["module", "list"]) == 0
    assert cli.main(["config", "show"]) == 0


def test_template_list_ohne_modulvorlagen(capsys):
    _write_modules(["proxmox"])
    assert cli.main(["template", "list"]) == 0
    names = {line.split()[0] for line in capsys.readouterr().out.splitlines() if line.strip()}
    assert "vm-lxc" in names and "gefriergut" in names
    assert "asn" not in names and "datentraeger" not in names
