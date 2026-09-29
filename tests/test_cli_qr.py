import io
import json
import sys

import pytest
from PIL import Image

from tapesmith import cli
from tapesmith.cli_cmds import base as cmd_base
from tapesmith.cli_cmds import qr as qr_cmd


def test_url_qr_preview_writes_png_and_info(tmp_path, capsys):
    png = tmp_path / "u.png"
    assert cli.main(["qr", "url", "l.lan/d7", "--line", "Doku", "--preview", str(png)]) == 0
    assert png.exists()
    with Image.open(png) as img:
        assert img.size[0] > 0
    assert "Info: QR Version" in capsys.readouterr().err


def test_text_qr_too_long_is_exit_1_auto_and_fixed_error(tmp_path, capsys):
    png = tmp_path / "t.png"
    assert cli.main(["qr", "text", "x" * 300, "--preview", str(png)]) == 1
    err = capsys.readouterr().err
    assert "passt nicht lesbar" in err and "Kurz-Link" in err
    assert not png.exists()

    assert cli.main(["qr", "text", "x" * 300, "--error", "m", "--preview", str(png)]) == 1
    err = capsys.readouterr().err
    assert "passt nicht lesbar" in err and "Kurz-Link" in err
    assert not png.exists()


def test_wifi_qr_password_stdin_show_data_hides_password(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO("geheim123\n"))
    png = tmp_path / "w.png"
    rc = cli.main(["qr", "wifi", "--ssid", "Heim", "--password-stdin", "--show-data",
                   "--preview", str(png)])
    assert rc == 0
    out, err = capsys.readouterr()
    assert "•••" in out
    assert "geheim123" not in out
    assert "geheim123" not in err


def test_wifi_qr_password_env(tmp_path, monkeypatch, capsys):
    png = tmp_path / "w.png"
    monkeypatch.delenv("P12_TEST_PW", raising=False)
    assert cli.main(["qr", "wifi", "--ssid", "Heim", "--password-env", "P12_TEST_PW",
                      "--preview", str(png)]) == 1

    monkeypatch.setenv("P12_TEST_PW", "geheim123")
    assert cli.main(["qr", "wifi", "--ssid", "Heim", "--password-env", "P12_TEST_PW",
                      "--preview", str(png)]) == 0


def test_wifi_qr_password_prompt(tmp_path, monkeypatch):
    monkeypatch.setattr(qr_cmd, "GETPASS", lambda prompt: "x1234567")
    png = tmp_path / "w.png"
    assert cli.main(["qr", "wifi", "--ssid", "Heim", "--password-prompt",
                      "--preview", str(png)]) == 0


def test_qr_prints_via_file_transport(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "SLEEP", lambda s: None)
    job = tmp_path / "job.bin"
    assert cli.main(["--transport", f"file:{job}", "qr", "text", "Hallo"]) == 0
    assert "1b401d763000" in job.read_bytes().hex()


def test_qr_emits_metadata_without_the_password(tmp_path, monkeypatch):
    monkeypatch.setenv("P12_TEST_PW", "geheim123")
    captured = {}

    def fake(ctx, result, meta):
        captured["meta"] = meta
        return False

    monkeypatch.setattr(cmd_base, "default_emit_label", fake)
    png = tmp_path / "w.png"
    assert cli.main(["qr", "wifi", "--ssid", "Heim", "--password-env", "P12_TEST_PW",
                      "--preview", str(png)]) == 0
    meta = captured["meta"]
    assert meta.sensitive is True
    assert "geheim123" not in json.dumps(meta.to_dict())
    # Nachdruckbar ohne Klartext: SSID/Sicherheit/Layout gespeichert, Passwort maskiert
    assert meta.values["qr_kind"] == "wifi"
    assert meta.values["ssid"] == "Heim"
    assert meta.values["password"] == "•••"
    assert meta.spec is None


def test_qr_appears_in_help(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    assert "qr" in capsys.readouterr().out
