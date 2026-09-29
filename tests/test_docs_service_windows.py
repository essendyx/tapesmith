"""Doku-Tests für den README-Abschnitt 'Dienst & Windows' und die
Hardware-Prüfliste (`docs/hardware/README.md`)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tapesmith import cli
from tapesmith.config import SECTION_DEFAULTS

REPO_ROOT = Path(__file__).resolve().parent.parent
README = (REPO_ROOT / "docs" / "handbuch.md").read_text(encoding="utf-8")  # deutsches Handbuch
HARDWARE_README = (REPO_ROOT / "docs" / "hardware" / "README.md").read_text(encoding="utf-8")

SERVICE_HEADING = "## Dienst & Windows"

SUBSECTIONS = (
    "### Druckdienst p12d",
    "### Warteschlange",
    "### Tray-App und Hotkeys",
    "### Zwischenablage",
    "### Kontextmenü und URI",
    "### Kommandopalette und Tastenkürzel",
    "### Datenträger-Assistent",
    "### Statusanzeige",
    "### Experimentell: Blockmodus, BLE, USB",
    "### SSH-Disk-Scanner",
    "### Verlauf, Archiv, Statistik, Inventar",
    "### Sicherung, Konfiguration als Code, Nummernkreise",
    "### Entwicklerwerkzeuge",
    "### Neue Einstellungen",
)

REQUIRED_TERMS = (
    "p12 daemon", "--no-daemon", "p12 queue", "Strg+Alt+L", "AltGr",
    "p12 integrate install", "tapesmith://print?template=datentraeger", "Strg+K",
    "block_rows", "p12 ble scan", "experimental", "id_ed25519_homelab", "numbering.dir",
    "p12 raw", "--unsafe", "hci-snoop.md", "phomemo_print_p12",
)

SECRET_MARKERS = ("BEGIN OPENSSH PRIVATE KEY", "ghp_", "password=")

SETTINGS_SECTIONS = (
    "daemon", "queue", "status", "hotkey", "tray", "ble", "ssh", "archive", "backup", "numbering",
)

CLI_COMMANDS = (
    "daemon", "queue", "tray", "integrate", "drives", "disks", "inv", "stats", "archive",
    "backup", "config", "nummern", "raw", "density", "ble", "usb",
)

HARDWARE_HEADING = "## Dienst und Windows: offen für den Gerätetest"


def test_service_heading_present():
    assert SERVICE_HEADING in README


def test_service_subsections_in_order():
    positions = []
    for heading in SUBSECTIONS:
        assert heading in README, f"Überschrift fehlt: {heading}"
        positions.append(README.index(heading))
    assert positions == sorted(positions), "Reihenfolge der Unterabschnitte stimmt nicht"
    assert README.index(SERVICE_HEADING) < positions[0]


@pytest.mark.parametrize("term", REQUIRED_TERMS)
def test_required_term_present(term):
    assert term in README, f"Begriff fehlt im README: {term!r}"


@pytest.mark.parametrize("section", SETTINGS_SECTIONS)
def test_settings_table_covers_section_defaults(section):
    for key in SECTION_DEFAULTS[section]:
        needle = f"`{section}.{key}`"
        assert needle in README, f"Einstellungs-Tabelle nennt {needle} nicht"


@pytest.mark.parametrize("marker", SECRET_MARKERS)
def test_no_secret_like_strings(marker):
    assert marker not in README


def test_ssh_key_only_as_path():
    assert "%USERPROFILE%" in README


def test_hardware_readme_has_service_section():
    assert HARDWARE_HEADING in HARDWARE_README


def test_hardware_readme_has_exactly_12_entries():
    idx = HARDWARE_README.index(HARDWARE_HEADING)
    section = HARDWARE_README[idx:]
    # Bis zum nächsten "## "-Abschnitt (falls vorhanden) begrenzen.
    next_heading = section.find("\n## ", len(HARDWARE_HEADING))
    if next_heading != -1:
        section = section[:next_heading]
    entries = re.findall(r"^\d+\. ", section, re.M)
    assert len(entries) == 12, f"Erwartet 12 nummerierte Einträge, gefunden: {len(entries)}"


def test_hardware_readme_entry_6_mentions_mac_query():
    idx = HARDWARE_README.index(HARDWARE_HEADING)
    section = HARDWARE_README[idx:]
    entry_6 = re.search(r"^6\. (.*)$", section, re.M)
    assert entry_6 is not None
    assert "1F 11 20" in entry_6.group(1)


def test_hardware_readme_entry_12_mentions_print_master():
    idx = HARDWARE_README.index(HARDWARE_HEADING)
    section = HARDWARE_README[idx:]
    entry_12 = re.search(r"^12\. (.*)$", section, re.M)
    assert entry_12 is not None
    assert "Print-Master" in entry_12.group(1)


@pytest.mark.parametrize("befehl", CLI_COMMANDS)
def test_cli_command_registered(befehl, capsys):
    assert f"p12 {befehl}" in README, f"README erwähnt 'p12 {befehl}' nicht"
    with pytest.raises(SystemExit) as excinfo:
        cli.main([befehl, "--help"])
    capsys.readouterr()
    assert excinfo.value.code == 0
