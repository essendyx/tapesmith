"""CLI-Befehl `tapesmith homelab` (show, set, check, secret, path)."""

import io
import json
import sys

from homelab_fakes import FakeKeyring, missing_refs, token_file, write_homelab
from tapesmith import cli
from tapesmith.integrations import settings


def test_homelab_in_help(capsys):
    try:
        cli.main(["--help"])
    except SystemExit:
        pass
    assert "homelab" in capsys.readouterr().out


def test_show_prints_json(tmp_path, capsys):
    write_homelab(missing_refs(tmp_path))
    assert cli.main(["homelab", "show"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["assets"]["prefix"] == "HL-"
    assert data["paperless"]["token_set"] is False


def test_set_changes_file(capsys):
    assert cli.main(["homelab", "set", "assets.prefix", '"AS-"']) == 0
    stored = json.loads(settings.settings_path().read_text(encoding="utf-8"))
    assert stored == {"assets": {"prefix": "AS-"}}
    assert cli.main(["homelab", "set", "kabel.prefix", "KB-"]) == 0
    assert cli.main(["homelab", "set", "paperless.public_url", "null"]) == 0
    assert cli.main(["homelab", "set", "assets.check_digit", "true"]) == 0
    data = settings.load_settings()
    assert data["kabel"]["prefix"] == "KB-"
    assert data["assets"]["check_digit"] is True


def test_set_invalid_is_exit_1(capsys):
    assert cli.main(["homelab", "set", "assets.width", "99"]) == 1
    assert "assets.width" in capsys.readouterr().err
    assert not settings.settings_path().exists()


def test_check_lists_services(tmp_path, capsys):
    data = missing_refs(tmp_path)
    data["paperless"]["token_ref"] = token_file(tmp_path, "p")
    write_homelab(data)
    assert cli.main(["homelab", "check"]) == 0
    out = capsys.readouterr().out
    for label in ("Paperless", "Proxmox", "Obsidian", "Home Assistant", "Kurz-Link-Dienst"):
        assert label in out
    assert "ok" in out and "fehlt" in out
    assert "✓" not in out and "✗" not in out


def test_path(capsys):
    assert cli.main(["homelab", "path"]) == 0
    assert capsys.readouterr().out.strip() == str(settings.settings_path())


def test_secret_with_fake_keyring(monkeypatch, capsys):
    fake = FakeKeyring()
    monkeypatch.setitem(sys.modules, "keyring", fake)
    monkeypatch.setattr(sys, "stdin", io.StringIO("neuer-wert\n"))
    assert cli.main(["homelab", "secret", "tapesmith/paperless", "--stdin"]) == 0
    assert fake.entries == {("tapesmith", "paperless"): "neuer-wert"}
    captured = capsys.readouterr()
    assert "neuer-wert" not in captured.out + captured.err


def test_secret_with_getpass(monkeypatch, capsys):
    fake = FakeKeyring()
    monkeypatch.setitem(sys.modules, "keyring", fake)
    from tapesmith.cli_cmds import homelab as homelab_cmd

    monkeypatch.setattr(homelab_cmd.getpass, "getpass", lambda prompt="": "verdeckt")
    assert cli.main(["homelab", "secret", "tapesmith/ha"]) == 0
    assert fake.entries == {("tapesmith", "ha"): "verdeckt"}


def test_secret_without_keyring_package(monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "keyring", None)
    monkeypatch.setattr(sys, "stdin", io.StringIO("x\n"))
    assert cli.main(["homelab", "secret", "tapesmith/paperless", "--stdin"]) == 1
    assert "keyring" in capsys.readouterr().err


def test_secret_empty_value_is_exit_1(monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "keyring", FakeKeyring())
    monkeypatch.setattr(sys, "stdin", io.StringIO("\n"))
    assert cli.main(["homelab", "secret", "tapesmith/paperless", "--stdin"]) == 1


def test_secret_invalid_name_is_exit_1(monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "keyring", FakeKeyring())
    monkeypatch.setattr(sys, "stdin", io.StringIO("x\n"))
    assert cli.main(["homelab", "secret", "nurname", "--stdin"]) == 1
