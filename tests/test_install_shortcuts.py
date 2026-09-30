"""Tests für `tapesmith.install.shortcuts` (Startmenü-Verknüpfungen).

Ausschließlich `FakeShortcuts`; `PowerShellShortcuts` wird nur auf den Sicherheitsnetz-Schutz
gegen echte Schreibzugriffe unter pytest geprüft, nie wirklich aufgerufen."""

from __future__ import annotations

import pytest

from tapesmith.install import shortcuts as sc


# ---------- FakeShortcuts ----------

def test_fake_create_und_exists(tmp_path):
    backend = sc.FakeShortcuts()
    link = tmp_path / "Tapesmith.lnk"
    target = tmp_path / "Tapesmith.exe"

    backend.create(link, target, arguments="--uninstall", description="Text")

    assert backend.exists(link) is True
    entry = backend.items[link]
    assert entry["target"] == target
    assert entry["arguments"] == "--uninstall"
    assert entry["description"] == "Text"


def test_fake_delete(tmp_path):
    backend = sc.FakeShortcuts()
    link = tmp_path / "Tapesmith.lnk"
    backend.create(link, tmp_path / "Tapesmith.exe")
    assert backend.exists(link) is True

    backend.delete(link)

    assert backend.exists(link) is False


def test_fake_delete_unbekannter_pfad_kein_fehler(tmp_path):
    backend = sc.FakeShortcuts()
    backend.delete(tmp_path / "fehlt.lnk")  # darf nicht werfen


# ---------- PowerShellShortcuts: Sicherheitsnetz ----------

def test_powershell_create_unter_pytest_wirft():
    backend = sc.PowerShellShortcuts()
    with pytest.raises(RuntimeError, match="Test"):
        backend.create("C:/x.lnk", "C:/x.exe")


def test_powershell_delete_unter_pytest_wirft():
    backend = sc.PowerShellShortcuts()
    with pytest.raises(RuntimeError, match="Test"):
        backend.delete("C:/x.lnk")


def test_powershell_exists_bleibt_erlaubt(tmp_path):
    backend = sc.PowerShellShortcuts()
    assert backend.exists(tmp_path / "fehlt.lnk") is False


# ---------- start_menu_dir ----------

def test_start_menu_dir_mit_override(tmp_path, monkeypatch):
    monkeypatch.setenv("TAPESMITH_START_MENU_DIR", str(tmp_path / "menu"))
    assert sc.start_menu_dir() == tmp_path / "menu"


def test_start_menu_dir_ohne_override_unter_pytest_wirft(monkeypatch):
    monkeypatch.delenv("TAPESMITH_START_MENU_DIR", raising=False)
    with pytest.raises(RuntimeError, match="TAPESMITH_START_MENU_DIR"):
        sc.start_menu_dir()
