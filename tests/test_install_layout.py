"""Tests für `tapesmith.install.layout` (Wurzel, Zustand, Versionsvergleich)."""

from __future__ import annotations

import pytest

from tapesmith.install import layout


# ---------- install_root ----------

def test_install_root_mit_override(tmp_path, monkeypatch):
    monkeypatch.setenv("TAPESMITH_INSTALL_ROOT", str(tmp_path / "wurzel"))
    assert layout.install_root() == tmp_path / "wurzel"


def test_install_root_ohne_override_unter_pytest_wirft(monkeypatch):
    monkeypatch.delenv("TAPESMITH_INSTALL_ROOT", raising=False)
    with pytest.raises(RuntimeError, match="TAPESMITH_INSTALL_ROOT"):
        layout.install_root()


def test_install_root_legt_nichts_an(tmp_path, monkeypatch):
    root = tmp_path / "nicht-vorhanden"
    monkeypatch.setenv("TAPESMITH_INSTALL_ROOT", str(root))
    layout.install_root()
    assert not root.exists()


# ---------- parse_version ----------

@pytest.mark.parametrize("a, b", [
    ("0.10.1", "0.9.9"),
    ("1.0.0", "0.99.99"),
    ("0.2.1", "0.2.0"),
    ("0.2.0", "0.2.0-beta.1"),
    ("0.2.0-beta.2", "0.2.0-beta.1"),
    ("0.2.0-beta.10", "0.2.0-beta.9"),
])
def test_parse_version_groesser(a, b):
    assert layout.parse_version(a) > layout.parse_version(b)


def test_parse_version_gleich():
    assert layout.parse_version("0.2.0") == layout.parse_version("0.2.0")


def test_parse_version_ungueltig_wirft():
    with pytest.raises(ValueError):
        layout.parse_version("nicht-eine-version")


# ---------- InstallState: to_dict / from_dict ----------

def test_install_state_roundtrip():
    state = layout.InstallState(current="0.2.1", previous="0.2.0", versions=["0.2.0", "0.2.1"],
                                failed=["0.1.9"], installed_at="2026-09-28T10:00:00+00:00",
                                channel="stable")
    data = state.to_dict()
    assert data["schema"] == 1
    restored = layout.InstallState.from_dict(data)
    assert restored == state


def test_install_state_from_dict_fehlende_felder_haben_defaults():
    restored = layout.InstallState.from_dict({})
    assert restored.current is None
    assert restored.previous is None
    assert restored.versions == []
    assert restored.failed == []
    assert restored.channel == "stable"


# ---------- read_state / write_state ----------

def test_read_state_fehlende_datei_gibt_none(tmp_path):
    assert layout.read_state(tmp_path) is None


def test_write_state_dann_read_state(tmp_path):
    state = layout.InstallState(current="0.2.0", versions=["0.2.0"], installed_at="jetzt")
    layout.write_state(state, tmp_path)
    assert layout.read_state(tmp_path) == state
    assert (tmp_path / "install.json").exists()


def test_write_state_schreibt_atomar_kein_tmp_rest(tmp_path):
    layout.write_state(layout.InstallState(current="0.1.0"), tmp_path)
    leftovers = [p for p in tmp_path.iterdir() if p.suffix == ".tmp"]
    assert leftovers == []


def test_read_state_kaputtes_json_wirft_klartext(tmp_path):
    (tmp_path / "install.json").write_text("{kaputt", encoding="utf-8")
    with pytest.raises(ValueError, match="install.json"):
        layout.read_state(tmp_path)


# ---------- Pfade ----------

def test_version_dir(tmp_path):
    assert layout.version_dir("0.2.0", tmp_path) == tmp_path / "versions" / "0.2.0"


def test_current_link_und_exe(tmp_path):
    assert layout.current_link(tmp_path) == tmp_path / "current"
    assert layout.current_exe(tmp_path) == tmp_path / "current" / "Tapesmith.exe"


# ---------- running_installed ----------

def test_running_installed_unter_versions(tmp_path):
    exe = tmp_path / "versions" / "0.2.0" / "Tapesmith.exe"
    assert layout.running_installed(str(exe), tmp_path) is True


def test_running_installed_unter_current(tmp_path):
    exe = tmp_path / "current" / "Tapesmith.exe"
    assert layout.running_installed(str(exe), tmp_path) is True


def test_running_installed_gross_klein_egal(tmp_path):
    exe = str(tmp_path / "CURRENT" / "Tapesmith.exe").upper()
    assert layout.running_installed(exe, tmp_path) is True


def test_running_installed_ausserhalb_false(tmp_path):
    exe = tmp_path / "Sonstwo" / "Tapesmith.exe"
    assert layout.running_installed(str(exe), tmp_path) is False
