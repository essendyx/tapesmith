"""Verdrahtung der CLI: Pipeline, Kopien/Kette, Rückfragen, Klartext-Fehler, Nachdruck."""

import _thread
import io
import json
import sys
import time
import tomllib
from pathlib import Path

import pytest

from tapesmith import cli, paths
from tapesmith.cli_cmds import base
from tapesmith.device.profile import load_profile
from tapesmith.history import HistoryStore
from tapesmith.transport.base import ConnectTimeout, MemoryTransport, TransportError

GOLDEN = Path(__file__).parent / "golden"
ROOT = Path(__file__).parent.parent
HEADER = bytes.fromhex("1b401d763000")


@pytest.fixture(autouse=True)
def _no_sleep_no_tty(monkeypatch):
    monkeypatch.setattr(cli, "SLEEP", lambda s: None)
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))


def raster_headers(data: bytes) -> int:
    return data.count(HEADER)


def from_header(data: bytes) -> bytes:
    return data[data.index(HEADER):]


def entries() -> list:
    with HistoryStore() as store:
        return store.search("", limit=100)


class FakeTty(io.StringIO):
    def isatty(self):
        return True


# 1
def test_golden_print_image_unchanged(tmp_path):
    out = tmp_path / "job.bin"
    assert cli.main(["--transport", f"file:{out}", "print-image", str(GOLDEN / "ref_label.pbm")]) == 0
    assert out.read_bytes() == (GOLDEN / "ref_stream.bin").read_bytes()


# 2
def test_copies_print_single_jobs(tmp_path, capsys):
    job = tmp_path / "j.bin"
    assert cli.main(["--transport", f"file:{job}", "text", "K1", "--length-mm", "20", "--copies", "3"]) == 0
    assert raster_headers(job.read_bytes()) == 3
    out = capsys.readouterr().out
    assert "Band:" in out and "3 Labels" in out


# 3
def test_chain_prints_one_job(tmp_path, capsys):
    job = tmp_path / "j.bin"
    assert cli.main(["--transport", f"file:{job}", "text", "K1", "--length-mm", "20",
                     "--copies", "3", "--chain"]) == 0
    assert raster_headers(job.read_bytes()) == 1
    assert "statt" in capsys.readouterr().out


# 4
def test_confirmation_without_tty_needs_yes(tmp_path, capsys):
    job = tmp_path / "j.bin"
    args = ["--transport", f"file:{job}", "text", "K1", "--length-mm", "20", "--copies", "6"]
    assert cli.main(args) == 1
    assert "--yes" in capsys.readouterr().err
    assert not job.exists() or job.read_bytes() == b""
    assert cli.main([*args, "--yes"]) == 0
    assert raster_headers(job.read_bytes()) == 6


# 5
@pytest.mark.parametrize("answer, code", [("j\n", 0), ("n\n", 1)])
def test_confirmation_with_tty(tmp_path, capsys, monkeypatch, answer, code):
    monkeypatch.setattr(sys, "stdin", FakeTty(answer))
    job = tmp_path / "j.bin"
    assert cli.main(["--transport", f"file:{job}", "text", "K1", "--length-mm", "20", "--copies", "6"]) == code
    err = capsys.readouterr().err
    assert "Rückfrage" in err
    if code == 0:
        assert raster_headers(job.read_bytes()) == 6
    else:
        assert "Nicht gedruckt" in err
        assert not job.exists() or job.read_bytes() == b""


# 6
def test_hard_limit(tmp_path, capsys):
    job = tmp_path / "j.bin"
    assert cli.main(["--transport", f"file:{job}", "text", "K1", "--copies", "51", "--yes"]) == 1
    assert "Obergrenze" in capsys.readouterr().err


# 7
def test_history_and_reprint_last(tmp_path, capsys):
    job1, job2 = tmp_path / "a.bin", tmp_path / "b.bin"
    assert cli.main(["--transport", f"file:{job1}", "text", "SN 274913"]) == 0
    capsys.readouterr()
    assert cli.main(["history", "274913"]) == 0
    out = capsys.readouterr().out
    assert "SN 274913" in out and "ok" in out
    assert cli.main(["--transport", f"file:{job2}", "reprint", "last"]) == 0
    assert from_header(job2.read_bytes()) == from_header(job1.read_bytes())


# 7b
def test_reprint_keeps_copies_and_chain(tmp_path):
    job_a, job_b = tmp_path / "a.bin", tmp_path / "b.bin"
    assert cli.main(["--transport", f"file:{job_a}", "text", "K1", "--length-mm", "20",
                     "--copies", "2", "--chain"]) == 0
    data_a = job_a.read_bytes()
    assert raster_headers(data_a) == 1
    rows = int.from_bytes(from_header(data_a)[8:10], "little")
    assert rows > 2 * 160                                  # Schnittzone zwischen den Labels
    assert cli.main(["--transport", f"file:{job_b}", "reprint", "last"]) == 0
    data_b = job_b.read_bytes()
    assert raster_headers(data_b) == 1
    assert data_b == data_a
    newest = entries()[0]
    assert newest.kind == "reprint"
    assert newest.copies == 2
    assert newest.chained is True


# 7c
def test_reprint_single_copies_and_override(tmp_path):
    job, job_c, job_d = tmp_path / "a.bin", tmp_path / "c.bin", tmp_path / "d.bin"
    assert cli.main(["--transport", f"file:{job}", "text", "K1", "--length-mm", "20", "--copies", "3"]) == 0
    assert cli.main(["--transport", f"file:{job_c}", "reprint", "last"]) == 0
    assert raster_headers(job_c.read_bytes()) == 3
    assert cli.main(["--transport", f"file:{job_d}", "reprint", "last", "--copies", "1"]) == 0
    assert raster_headers(job_d.read_bytes()) == 1


# 7d
def test_reprint_long_chain_keeps_job_split(tmp_path):
    job, job2 = tmp_path / "a.bin", tmp_path / "b.bin"
    assert cli.main(["--transport", f"file:{job}", "text", "Kabel 01", "--length-mm", "30",
                     "--copies", "10", "--chain", "--yes"]) == 0
    assert raster_headers(job.read_bytes()) == 2
    assert cli.main(["--transport", f"file:{job2}", "reprint", "last", "--yes"]) == 0
    assert raster_headers(job2.read_bytes()) == 2


def test_reprint_by_id_and_empty_history(tmp_path, capsys):
    assert cli.main(["--transport", f"file:{tmp_path / 'x.bin'}", "reprint", "last"]) == 1
    assert "leer" in capsys.readouterr().err
    job = tmp_path / "a.bin"
    assert cli.main(["--transport", f"file:{job}", "text", "Eins"]) == 0
    first_id = entries()[0].id
    assert cli.main(["--transport", f"file:{job}", "text", "Zwei"]) == 0
    job2 = tmp_path / "b.bin"
    assert cli.main(["--transport", f"file:{job2}", "reprint", str(first_id)]) == 0
    assert "Nachdruck #" in entries()[0].title
    assert "Eins" in entries()[0].title


# 8
def _wlan_template():
    tpl_dir = paths.app_dir() / "templates"
    tpl_dir.mkdir(exist_ok=True)
    (tpl_dir / "wlan.tapesmith.json").write_text(json.dumps({
        "schema_version": 1, "name": "wlan", "description": "WLAN",
        "fields": [
            {"id": "ssid", "label": "SSID", "type": "input", "required": True},
            {"id": "pw", "label": "Passwort", "type": "input", "secret": True, "required": True},
        ],
        "layout": {"lines": ["{ssid}"], "qr": "WIFI:T:WPA;S:{ssid};P:{pw};;"},
    }), encoding="utf-8")


def _db_bytes() -> bytes:
    db = paths.history_db_path()
    return b"".join(p.read_bytes() for p in db.parent.glob(db.name + "*"))


def test_sensitive_template_reprint(tmp_path, capsys, monkeypatch):
    from tapesmith.cli_cmds import reprint as reprint_cmd

    _wlan_template()
    job = tmp_path / "a.bin"
    assert cli.main(["--transport", f"file:{job}", "template", "print", "wlan",
                     "--set", "ssid=Gast", "--set", "pw=geheim123"]) == 0
    capsys.readouterr()
    assert cli.main(["history", "--json"]) == 0
    out = capsys.readouterr().out
    assert "•••" in out and "geheim123" not in out
    assert b"geheim123" not in _db_bytes()

    job2 = tmp_path / "b.bin"
    assert cli.main(["--transport", f"file:{job2}", "reprint", "last"]) == 6
    assert "--prompt pw" in capsys.readouterr().err

    monkeypatch.setattr(reprint_cmd, "GETPASS", lambda prompt: "geheim123")
    assert cli.main(["--transport", f"file:{job2}", "reprint", "last", "--prompt", "pw"]) == 0
    assert raster_headers(job2.read_bytes()) == 1
    capsys.readouterr()
    assert cli.main(["history", "--json"]) == 0
    assert "geheim123" not in capsys.readouterr().out
    assert b"geheim123" not in _db_bytes()

    job3 = tmp_path / "c.bin"
    assert cli.main(["--transport", f"file:{job3}", "reprint", "last", "--set", "pw=geheim123"]) == 0
    assert raster_headers(job3.read_bytes()) == 1


def test_wifi_qr_reprint_prompts_password(tmp_path, capsys, monkeypatch):
    from tapesmith.cli_cmds import reprint as reprint_cmd

    monkeypatch.setenv("P12_TEST_PW", "geheim123")
    job = tmp_path / "a.bin"
    assert cli.main(["--transport", f"file:{job}", "qr", "wifi", "--ssid", "Gast",
                     "--password-env", "P12_TEST_PW", "--line", "Gast-WLAN"]) == 0
    capsys.readouterr()
    assert b"geheim123" not in _db_bytes()

    job2 = tmp_path / "b.bin"
    assert cli.main(["--transport", f"file:{job2}", "reprint", "last"]) == 6
    assert "--prompt password" in capsys.readouterr().err

    monkeypatch.setattr(reprint_cmd, "GETPASS", lambda prompt: "geheim123")
    assert cli.main(["--transport", f"file:{job2}", "reprint", "last", "--prompt", "password"]) == 0
    assert raster_headers(job2.read_bytes()) == 1
    assert from_header(job2.read_bytes()) == from_header(job.read_bytes())
    assert b"geheim123" not in _db_bytes()


# 9
def test_export_and_preview(tmp_path, capsys):
    pdf, png = tmp_path / "l.pdf", tmp_path / "v.png"
    job = tmp_path / "j.bin"
    assert cli.main(["--transport", f"file:{job}", "text", "SSD-1", "--export", str(pdf),
                     "--preview", str(png)]) == 0
    assert pdf.is_file() and png.is_file()
    assert not job.exists()
    out = capsys.readouterr().out
    assert "Export:" in out and "Vorschau:" in out

    pbm = tmp_path / "l.pbm"
    assert cli.main(["--transport", f"file:{job}", "text", "SSD-1", "--export", str(pbm)]) == 0
    assert pbm.is_file()
    assert raster_headers(job.read_bytes()) == 1


def test_preview_with_copies_shows_balance(tmp_path, capsys):
    png = tmp_path / "v.png"
    assert cli.main(["text", "K1", "--length-mm", "20", "--copies", "3", "--chain",
                     "--preview", str(png)]) == 0
    assert png.is_file()
    assert "statt" in capsys.readouterr().out


# 10a
def _fake_open(monkeypatch, responses=None, calls=None):
    calls = [] if calls is None else calls

    def fake(spec, mac, hexlog=None, **kw):
        calls.append((spec, hexlog, kw))
        return MemoryTransport(responses or {})

    monkeypatch.setattr(cli, "open_transport", fake)
    return calls


def test_connect_timeout_from_config(monkeypatch):
    calls = _fake_open(monkeypatch)
    assert cli.main(["status"]) == 0
    assert calls[0][2]["open_timeout"] == 5.0
    assert calls[0][1] is None

    paths.config_path().write_text(json.dumps({"connect_timeout_s": 2}), encoding="utf-8")
    calls.clear()
    assert cli.main(["text", "x"]) == 0
    assert calls[0][2]["open_timeout"] == 2.0


# 10b
def test_hexlog_uses_device_codes(tmp_path, monkeypatch):
    _fake_open(monkeypatch, {bytes.fromhex("1f1112"): bytes.fromhex("1a0599")})
    log = tmp_path / "hex.log"
    assert cli.main(["--hexlog", str(log), "status"]) == 0
    text = log.read_text(encoding="utf-8")
    assert "Deckel offen" in text
    assert "Deckel zu" not in text


# 10
def test_plain_text_errors(monkeypatch, capsys):
    def busy(spec, mac, hexlog=None, **kw):
        raise TransportError("COM4: could not open port 'COM4': PermissionError(13, 'Zugriff verweigert', None, 5)")

    monkeypatch.setattr(cli, "open_transport", busy)
    assert cli.main(["text", "x"]) == 7
    err = capsys.readouterr().err
    assert "COM4 belegt" in err and "->" in err

    def timeout(spec, mac, hexlog=None, **kw):
        raise ConnectTimeout("COM4 antwortet nicht")

    monkeypatch.setattr(cli, "open_transport", timeout)
    assert cli.main(["text", "x"]) == 5
    assert "Nur ein Host" in capsys.readouterr().err


# 11
class FailingSecondBlock(MemoryTransport):
    def __init__(self):
        super().__init__()
        self.after_header = 0
        self.seen_header = False

    def write(self, data):
        if self.seen_header:
            self.after_header += 1
            if self.after_header == 2:
                raise TransportError("COM4: Semaphore timeout")
        if data.startswith(HEADER):
            self.seen_header = True
        super().write(data)


def test_incomplete_print(monkeypatch, capsys):
    t = FailingSecondBlock()
    monkeypatch.setattr(cli, "open_transport", lambda spec, mac, hexlog=None, **kw: t)
    assert cli.main(["text", "x", "--length-mm", "100"]) == 5
    assert "Druck unvollständig" in capsys.readouterr().err
    assert entries()[0].status == "unvollständig"


# 12
class InterruptingTransport(MemoryTransport):
    supports_responses = False

    def __init__(self):
        super().__init__()
        self.seen_header = False
        self.fired = False

    def write(self, data):
        super().write(data)
        if self.seen_header and not self.fired:
            self.fired = True
            _thread.interrupt_main()
            time.sleep(0.05)
        if HEADER in data:
            self.seen_header = True


def test_strg_c_abbruch(monkeypatch, capsys):
    monkeypatch.setattr(base, "JOIN_INTERVAL", 0.01)
    t = InterruptingTransport()
    monkeypatch.setattr(cli, "open_transport", lambda spec, mac, hexlog=None, **kw: t)
    assert cli.main(["text", "x", "--length-mm", "100"]) == 1
    assert "abgebrochen" in capsys.readouterr().err
    profile = load_profile()
    data = b"".join(t.written)
    assert data.endswith(profile.feed_command)
    body = from_header(data)
    rows = int.from_bytes(body[8:10], "little")
    assert rows == 800
    assert len(body) == 10 + rows * profile.bytes_per_line + len(profile.feed_command)
    assert entries()[0].status == "abgebrochen"


# 13
def test_preflight_warning_does_not_block(monkeypatch, capsys):
    _fake_open(monkeypatch, {bytes.fromhex("1f1112"): bytes.fromhex("1a0599")})
    assert cli.main(["text", "x"]) == 0
    captured = capsys.readouterr()
    assert "Warnung: Deckel offen" in captured.err
    assert "gedruckt" in captured.out


# 14
def test_fix_suggestions(tmp_path, capsys):
    job = tmp_path / "j.bin"
    args = ["--transport", f"file:{job}", "text", "pmx10 SSD-1 SN 274913", "--size", "60", "--max-mm", "30"]
    assert cli.main(args) == 1
    err = capsys.readouterr().err
    assert "Vorschläge:" in err and "--fix verkleinern" in err
    assert cli.main([*args, "--fix", "laenger"]) == 0
    assert "Korrektur: Länge auf" in capsys.readouterr().err


def test_print_fix_suggestions(tmp_path, capsys):
    args = ["print", "pmx10 SSD-1 SN 274913", "--size", "60", "--max-mm", "30",
            "--preview", str(tmp_path / "p.png")]
    assert cli.main(args) == 1
    assert "--fix verkleinern" in capsys.readouterr().err
    assert cli.main([*args, "--fix", "verkleinern"]) == 0
    assert "Korrektur:" in capsys.readouterr().err


# 15
def test_print_stdin_chain(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO("pmx10\n"))
    job = tmp_path / "j.bin"
    assert cli.main(["--transport", f"file:{job}", "print", "--copies", "2", "--chain"]) == 0
    assert raster_headers(job.read_bytes()) == 1


# 16
def test_probe_uses_device_codes(monkeypatch, capsys):
    _fake_open(monkeypatch, {bytes.fromhex("1f1112"): bytes.fromhex("1a0599")})
    assert cli.main(["probe", "1f1112"]) == 0
    assert "Deckel offen" in capsys.readouterr().out


# 17
def test_help_lists_commands(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    out = capsys.readouterr().out
    for cmd in ("status", "setup", "history", "qr", "print", "reprint"):
        assert cmd in out


# 18
def test_pyproject_has_compat_scripts():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    scripts = data["project"]["scripts"]
    assert scripts["p12"] == "tapesmith.cli:main"
    assert scripts["phomemo_render_label"] == "tapesmith.compat:main_render"
    assert scripts["phomemo_print_p12"] == "tapesmith.compat:main_print"


def test_pyproject_mcp_dependency_passt_zur_genutzten_2x_api():
    """`mcpserver/server.py` nutzt `mcp.server.mcpserver.MCPServer` (nur in der 2.x-Reihe des
    SDK vorhanden, nicht in 1.x): die Abhaengigkeit muss diese Version verlangen."""
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    deps = data["project"]["dependencies"]
    mcp_dep = next(d for d in deps if d.split(">=")[0].split("<")[0].strip() == "mcp")
    assert mcp_dep == "mcp>=2.2,<3"


def test_calibrate_ruler_needs_no_confirmation(tmp_path):
    job = tmp_path / "r.bin"
    assert cli.main(["--transport", f"file:{job}", "calibrate", "ruler", "--length-mm", "160"]) == 0
    assert raster_headers(job.read_bytes()) == 1
    assert entries()[0].kind == "calibrate"


def test_template_print_counts_only_when_printed(tmp_path):
    # Vorschau committet keinen Zähler, Druck schon (über die Pipeline)
    tpl = tmp_path / "z.tapesmith.json"
    tpl.write_text(json.dumps({
        "schema_version": 1, "name": "z", "description": "",
        "fields": [{"id": "nr", "label": "Nr", "type": "counter", "format": "N{:03d}"}],
        "layout": {"lines": ["{nr}"]},
    }), encoding="utf-8")
    counters = paths.app_dir() / "counters.json"
    assert cli.main(["template", "print", str(tpl), "--preview", str(tmp_path / "p.png")]) == 0
    assert not counters.exists()
    assert cli.main(["--transport", f"file:{tmp_path / 'j.bin'}", "template", "print", str(tpl)]) == 0
    assert json.loads(counters.read_text(encoding="utf-8")) == {"z.nr": 1}
    assert entries()[0].template == "z"
