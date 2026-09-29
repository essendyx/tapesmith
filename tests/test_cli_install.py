"""Tests für 'p12 install status' (nur lesend)."""

from __future__ import annotations

import json

from tapesmith.cli_cmds import install as install_cmd
from tapesmith.install import installer, layout
from tapesmith.install.registry import FakeUninstallRegistry


class _Ctx:
    def __init__(self):
        self.lines: list[str] = []

    def out(self, text: str) -> None:
        self.lines.append(text)


def _make_source(tmp_path, name="source"):
    src = tmp_path / name
    src.mkdir()
    (src / "Tapesmith.exe").write_bytes(b"exe")
    return src


def test_status_nicht_installiert(tmp_path, monkeypatch):
    monkeypatch.setenv("TAPESMITH_INSTALL_ROOT", str(tmp_path / "root"))
    monkeypatch.setattr(install_cmd, "BACKEND_FACTORY", FakeUninstallRegistry)

    data = install_cmd.status_dict()

    assert data == {"installed": False, "root": str(tmp_path / "root")}


def test_status_nach_installation_json(tmp_path, monkeypatch):
    root = tmp_path / "root"
    monkeypatch.setenv("TAPESMITH_INSTALL_ROOT", str(root))
    monkeypatch.setenv("TAPESMITH_START_MENU_DIR", str(tmp_path / "menu"))
    fake_reg = FakeUninstallRegistry()
    monkeypatch.setattr(install_cmd, "BACKEND_FACTORY", lambda: fake_reg)

    installer.install(_make_source(tmp_path), version="0.2.0", root=root, start=False)

    data = install_cmd.status_dict()

    assert data["installed"] is True
    assert data["current"] == "0.2.0"
    assert data["previous"] is None
    assert data["versions"] == ["0.2.0"]
    assert data["current_target"] is not None
    assert data["start_menu"] is False  # keine Verknüpfungen angelegt (shortcuts=None)
    assert data["uninstall_entry"] is False  # keine Registry angelegt (uninstall_registry=None)


def test_status_erkennt_uninstall_eintrag(tmp_path, monkeypatch):
    root = tmp_path / "root"
    monkeypatch.setenv("TAPESMITH_INSTALL_ROOT", str(root))
    monkeypatch.setenv("TAPESMITH_START_MENU_DIR", str(tmp_path / "menu"))
    fake_reg = FakeUninstallRegistry()
    monkeypatch.setattr(install_cmd, "BACKEND_FACTORY", lambda: fake_reg)

    installer.install(_make_source(tmp_path), version="0.2.0", root=root, start=False,
                      uninstall_registry=fake_reg)

    data = install_cmd.status_dict()

    assert data["uninstall_entry"] is True


def test_run_json(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TAPESMITH_INSTALL_ROOT", str(tmp_path / "root"))
    monkeypatch.setattr(install_cmd, "BACKEND_FACTORY", FakeUninstallRegistry)
    ctx = _Ctx()

    import argparse
    args = argparse.Namespace(install_cmd="status", json=True)
    code = install_cmd.run(args, ctx)

    assert code == 0
    assert len(ctx.lines) == 1
    data = json.loads(ctx.lines[0])
    assert data["installed"] is False


def test_run_text_ohne_installation(tmp_path, monkeypatch):
    monkeypatch.setenv("TAPESMITH_INSTALL_ROOT", str(tmp_path / "root"))
    monkeypatch.setattr(install_cmd, "BACKEND_FACTORY", FakeUninstallRegistry)
    ctx = _Ctx()

    import argparse
    args = argparse.Namespace(install_cmd="status", json=False)
    code = install_cmd.run(args, ctx)

    assert code == 0
    assert ctx.lines == ["nicht installiert"]


def test_register_baut_status_unterbefehl():
    import argparse
    parser = argparse.ArgumentParser()
    install_cmd.register(parser)
    args = parser.parse_args(["status", "--json"])
    assert args.install_cmd == "status"
    assert args.json is True


def test_hilfetext_verweist_auf_exe():
    assert "Tapesmith.exe --install" in install_cmd.INSTALL_HINT
