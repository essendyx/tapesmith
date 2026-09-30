"""Tests für `tapesmith.install.registry` (Apps-&-Features-Eintrag).

Ausschließlich `FakeUninstallRegistry`; `UninstallRegistry` wird nur auf das
Sicherheitsnetz gegen echte Schreibzugriffe unter pytest geprüft."""

from __future__ import annotations

from pathlib import Path

import pytest

from tapesmith.install import registry as reg_mod


def test_write_uninstall_entry_setzt_alle_werte():
    backend = reg_mod.FakeUninstallRegistry()

    reg_mod.write_uninstall_entry(backend, root=Path(r"C:\Users\x\AppData\Local\Programs\Tapesmith"),
                                  version="0.2.0", size_kb=12345)

    assert backend.values["DisplayName"] == "Tapesmith"
    assert backend.values["DisplayVersion"] == "0.2.0"
    assert backend.values["Publisher"] == "Tapesmith contributors"
    assert backend.values["InstallLocation"] == r"C:\Users\x\AppData\Local\Programs\Tapesmith"
    assert backend.values["DisplayIcon"] == \
        r"C:\Users\x\AppData\Local\Programs\Tapesmith\current\Lib\site-packages\tapesmith\icons\app.ico"
    # Keine eigene EXE: deinstalliert wird mit dem signierten pythonw.exe der aktiven Version.
    assert backend.values["UninstallString"] == \
        r'"C:\Users\x\AppData\Local\Programs\Tapesmith\current\Scripts\pythonw.exe" -m tapesmith uninstall'
    assert backend.values["QuietUninstallString"] == \
        r'"C:\Users\x\AppData\Local\Programs\Tapesmith\current\Scripts\pythonw.exe" -m tapesmith uninstall --quiet'
    assert backend.values["URLInfoAbout"] == "https://github.com/essendyx/tapesmith"
    assert backend.values["NoModify"] == 1
    assert isinstance(backend.values["NoModify"], int)
    assert backend.values["NoRepair"] == 1
    assert backend.values["EstimatedSize"] == 12345
    assert isinstance(backend.values["EstimatedSize"], int)


def test_remove_uninstall_entry_leert_backend():
    backend = reg_mod.FakeUninstallRegistry()
    reg_mod.write_uninstall_entry(backend, root=Path("C:/x"), version="0.1.0", size_kb=1)

    reg_mod.remove_uninstall_entry(backend)

    assert backend.values == {}
    assert backend.get("DisplayName") is None


def test_fake_get_unbekannter_wert_none():
    backend = reg_mod.FakeUninstallRegistry()
    assert backend.get("DisplayName") is None


def test_uninstall_registry_schreibmethoden_unter_pytest_wirft():
    backend = reg_mod.UninstallRegistry()
    with pytest.raises(RuntimeError, match="Test"):
        backend.set_str("DisplayName", "x")
    with pytest.raises(RuntimeError, match="Test"):
        backend.set_dword("NoModify", 1)
    with pytest.raises(RuntimeError, match="Test"):
        backend.delete_tree()


def test_uninstall_registry_get_bleibt_erlaubt():
    backend = reg_mod.UninstallRegistry()
    # Liest die echte Registry (kein Schreibzugriff, also unter pytest erlaubt); Testrechner
    # hat Tapesmith in aller Regel nicht installiert.
    assert backend.get("DisplayName") is None or isinstance(backend.get("DisplayName"), str)
