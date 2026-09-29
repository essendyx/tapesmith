"""Support-Bericht „Problem melden“."""

from __future__ import annotations

import io
import json
import sys
import zipfile
from datetime import datetime

import pytest

from tapesmith import config, paths, support
from webapi_fakes import close_ctx, make_client

NOW = datetime(2026, 9, 28, 14, 5, 0)


def _zip(data: bytes) -> zipfile.ZipFile:
    return zipfile.ZipFile(io.BytesIO(data))


def _all_text(zf: zipfile.ZipFile) -> str:
    return "\n".join(zf.read(name).decode("utf-8") for name in zf.namelist())


def _cfg(**extra) -> dict:
    cfg = dict(config.DEFAULTS)
    cfg.update(extra)
    return cfg


def test_dateiname():
    assert support.report_filename(NOW) == "tapesmith-bericht-20260928-1405.zip"


def test_mask_text():
    text = ("GET /api/v1/app X-P12-Token: abc123\n"
            "url http://pc:8712/familie?t=geheim&x=1\n"
            "Authorization: Bearer xyz\n"
            "http://pc:8712/#t=nochgeheim\n")
    masked = support.mask_text(text)
    for secret in ("abc123", "geheim", "xyz", "nochgeheim"):
        assert secret not in masked
    assert "X-P12-Token: ***" in masked
    assert "x=1" in masked


def test_mask_config():
    cfg = {"mqtt": {"password": "pw", "password_ref": "keyring:tapesmith/mqtt", "port": 1883},
           "update": {"token_ref": "keyring:tapesmith/github"},
           "api_key": "k1", "secret": ["s1"], "hotkey": {"quick": "Ctrl+Alt+L"}, "mac": "001122334455",
           "telegram": {"token_ref": None}}
    masked = support.mask_config(cfg)
    assert masked["mqtt"]["password"] == "***"
    assert masked["mqtt"]["password_ref"] == "keyring:tapesmith/mqtt"
    assert masked["mqtt"]["port"] == 1883
    assert masked["update"]["token_ref"] == "keyring:tapesmith/github"
    assert masked["api_key"] == "***"
    assert masked["secret"] == ["***"]
    assert masked["hotkey"]["quick"] == "Ctrl+Alt+L"
    assert masked["telegram"]["token_ref"] is None
    assert cfg["mqtt"]["password"] == "pw"          # Original unverändert


def test_bericht_inhalt_und_maskierung(app_home):
    logs = paths.log_dir()
    (logs / "p12d.log").write_text(
        "start\nX-P12-Token: abc123\nGET /familie?t=geheim\nAuthorization: Bearer xyz\n", encoding="utf-8")
    (logs / "p12d.log.1").write_text("alt\n", encoding="utf-8")
    (logs / "fremd.txt").write_text("nicht mitnehmen", encoding="utf-8")
    cfg = _cfg(mqtt={"password": "pw"}, update={"token_ref": "keyring:tapesmith/github"})
    status = {"view": {"chip": "P12 · verbunden", "title": "Tapesmith: verbunden (COM4)",
                       "detail": "Akku 75 %\nDeckel zu"},
              "queue": {"jobs": [{"id": 1}, {"id": 2}], "paused": False}}
    zf = _zip(support.build_report(cfg, status=status, now=NOW))
    names = set(zf.namelist())
    assert {"bericht.txt", "config.json", "logs/p12d.log", "logs/p12d.log.1"} <= names
    assert "logs/fremd.txt" not in names
    everything = _all_text(zf)
    for secret in ("abc123", "geheim", "xyz", '"pw"'):
        assert secret not in everything
    assert "keyring:tapesmith/github" in zf.read("config.json").decode("utf-8")
    assert json.loads(zf.read("config.json"))["mqtt"]["password"] == "***"

    report = zf.read("bericht.txt").decode("utf-8")
    import tapesmith

    assert f"Version: {tapesmith.__version__}" in report
    assert f"Python: {sys.version.split()[0]}" in report
    assert "Windows: " in report
    assert "Betrieb: Entwicklung" in report
    assert "Transport: auto" in report
    assert "Tapesmith: verbunden (COM4)" in report
    assert "Akku 75 %" in report
    assert "Warteschlange: 2 Aufträge" in report
    assert "\u2013" not in report and "\u2014" not in report


def test_bericht_ohne_status(app_home):
    zf = _zip(support.build_report(_cfg(), status=None, now=NOW))
    report = zf.read("bericht.txt").decode("utf-8")
    assert "Druckdienst nicht erreichbar" in report
    assert "Warteschlange: unbekannt" in report


def test_grosse_logs_werden_gekuerzt(app_home):
    big = ("x" * 99 + "\n") * 8000          # 800 KB
    (paths.log_dir() / "p12d.log").write_text("ANFANG\n" + big + "ENDE\n", encoding="utf-8")
    zf = _zip(support.build_report(_cfg(), status=None, now=NOW))
    data = zf.read("logs/p12d.log")
    assert len(data) <= support.MAX_LOG_BYTES + 200
    text = data.decode("utf-8")
    assert "ENDE" in text and "ANFANG" not in text
    assert "gekürzt" in text


@pytest.mark.parametrize("executable, frozen, expected", [
    (r"C:\Users\x\AppData\Local\Programs\Tapesmith\versions\0.2.0\Tapesmith.exe", True, "installiert"),
    (r"C:\Users\x\AppData\Local\Programs\Tapesmith\current\Tapesmith.exe", True, "installiert"),
    (r"D:\Tools\Tapesmith\Tapesmith.exe", True, "portabel"),
    (r"C:\src\tapesmith\.venv\Scripts\python.exe", False, "Entwicklung"),
])
def test_betriebsart(executable, frozen, expected):
    assert support.run_mode(executable=executable, frozen=frozen,
                            localappdata=r"C:\Users\x\AppData\Local") == expected


def test_route_support_report(tmp_path):
    client, ctx = make_client(tmp_path)
    try:
        (paths.log_dir() / "p12d.log").write_text("X-P12-Token: abc123\n", encoding="utf-8")
        r = client.post("/api/v1/support/report")
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/zip"
        disposition = r.headers["content-disposition"]
        assert disposition.startswith('attachment; filename="tapesmith-bericht-')
        assert disposition.endswith('.zip"')
        zf = _zip(r.content)
        assert "bericht.txt" in zf.namelist()
        assert "abc123" not in _all_text(zf)
        assert "Warteschlange: 0 Aufträge" in zf.read("bericht.txt").decode("utf-8")
    finally:
        close_ctx(ctx)


def test_route_support_report_status_fehler(tmp_path, monkeypatch):
    client, ctx = make_client(tmp_path)
    try:
        def boom(**kw):
            raise RuntimeError("kaputt")

        monkeypatch.setattr(ctx.service, "status", boom)
        r = client.post("/api/v1/support/report")
        assert r.status_code == 200
        assert "Druckdienst nicht erreichbar" in _zip(r.content).read("bericht.txt").decode("utf-8")
    finally:
        close_ctx(ctx)
