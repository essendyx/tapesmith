"""Tests für `tapesmith install` (Plugin-Befehl): `--status` bzw. `status` liest nur, ohne Status
leitet der Befehl an den Installer weiter."""

from __future__ import annotations

import argparse
import json

from tapesmith.cli_cmds import install as install_cmd
from tapesmith.cli_cmds import uninstall as uninstall_cmd
from tapesmith.install import installer
from tapesmith.install.registry import FakeUninstallRegistry
from update_fakes import PYTHON, FakeVenvRun


class _Ctx:
    def __init__(self):
        self.lines: list[str] = []

    def out(self, text: str) -> None:
        self.lines.append(text)


def _parse(argv):
    parser = argparse.ArgumentParser()
    install_cmd.register(parser)
    return parser.parse_args(argv)


def _install(root, **kw):
    return installer.install(version="0.2.0", root=root, python=PYTHON, run=FakeVenvRun(), start=False, **kw)


def test_status_nicht_installiert(tmp_path, monkeypatch):
    monkeypatch.setenv("TAPESMITH_INSTALL_ROOT", str(tmp_path / "root"))
    monkeypatch.setattr(install_cmd, "BACKEND_FACTORY", FakeUninstallRegistry)
    assert install_cmd.status_dict() == {"installed": False, "root": str(tmp_path / "root")}


def test_status_nach_installation_json(tmp_path, monkeypatch):
    root = tmp_path / "root"
    monkeypatch.setenv("TAPESMITH_INSTALL_ROOT", str(root))
    monkeypatch.setenv("TAPESMITH_START_MENU_DIR", str(tmp_path / "menu"))
    fake_reg = FakeUninstallRegistry()
    monkeypatch.setattr(install_cmd, "BACKEND_FACTORY", lambda: fake_reg)
    _install(root)

    data = install_cmd.status_dict()

    assert data["installed"] is True
    assert data["current"] == "0.2.0" and data["previous"] is None and data["versions"] == ["0.2.0"]
    assert data["current_target"] is not None and data["kind"] == "python"
    assert data["start_menu"] is False  # keine Verknüpfungen angelegt (shortcuts=None)
    assert data["uninstall_entry"] is False  # keine Registry angelegt (uninstall_registry=None)


def test_status_erkennt_uninstall_eintrag(tmp_path, monkeypatch):
    root = tmp_path / "root"
    monkeypatch.setenv("TAPESMITH_INSTALL_ROOT", str(root))
    monkeypatch.setenv("TAPESMITH_START_MENU_DIR", str(tmp_path / "menu"))
    fake_reg = FakeUninstallRegistry()
    monkeypatch.setattr(install_cmd, "BACKEND_FACTORY", lambda: fake_reg)
    _install(root, uninstall_registry=fake_reg)
    assert install_cmd.status_dict()["uninstall_entry"] is True


def test_run_json(tmp_path, monkeypatch):
    monkeypatch.setenv("TAPESMITH_INSTALL_ROOT", str(tmp_path / "root"))
    monkeypatch.setattr(install_cmd, "BACKEND_FACTORY", FakeUninstallRegistry)
    ctx = _Ctx()
    assert install_cmd.run(_parse(["--status", "--json"]), ctx) == 0
    assert len(ctx.lines) == 1
    assert json.loads(ctx.lines[0])["installed"] is False


def test_run_text_ohne_installation_auch_als_unterbefehl(tmp_path, monkeypatch):
    monkeypatch.setenv("TAPESMITH_INSTALL_ROOT", str(tmp_path / "root"))
    monkeypatch.setattr(install_cmd, "BACKEND_FACTORY", FakeUninstallRegistry)
    ctx = _Ctx()
    assert install_cmd.run(_parse(["status"]), ctx) == 0
    assert ctx.lines == [f"nicht installiert ({tmp_path / 'root'})"]


def test_run_ohne_status_installiert(monkeypatch):
    calls = []
    monkeypatch.setattr(installer, "run_args", lambda args: calls.append(args) or 0)
    args = _parse(["--no-registry", "--no-shortcuts", "--no-start"])
    assert install_cmd.run(args, _Ctx()) == 0
    assert calls == [args] and args.no_registry and args.no_start


def test_uninstall_befehl_leitet_weiter(monkeypatch):
    from tapesmith.install import uninstaller

    calls = []
    monkeypatch.setattr(uninstaller, "main", lambda argv: calls.append(argv) or 0)
    parser = argparse.ArgumentParser()
    uninstall_cmd.register(parser)
    args = parser.parse_args(["--no-registry", "--quiet", "--root", "C:/x"])
    assert uninstall_cmd.run(args, _Ctx()) == 0
    assert calls == [["--root", "C:/x", "--no-registry", "--quiet"]]
