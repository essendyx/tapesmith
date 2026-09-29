"""`p12 report --out DATEI.zip` (Support-Bericht, CLI bleibt Deutsch)."""

from __future__ import annotations

import zipfile

import pytest

from tapesmith import cli
from tapesmith.cli_cmds import report as report_cmd


@pytest.fixture(autouse=True)
def _kein_dienst(monkeypatch):
    calls = []

    def loader(cfg):
        calls.append(cfg)
        return None

    monkeypatch.setattr(report_cmd, "STATUS_LOADER", loader)
    return calls


def test_report_out(tmp_path, capsys, _kein_dienst):
    target = tmp_path / "bericht.zip"
    assert cli.main(["report", "--out", str(target)]) == 0
    out = capsys.readouterr().out
    assert out.strip() == f"Bericht gespeichert: {target} (keine Tokens enthalten)"
    with zipfile.ZipFile(target) as zf:
        assert "bericht.txt" in zf.namelist()
        assert "Druckdienst nicht erreichbar" in zf.read("bericht.txt").decode("utf-8")
    assert len(_kein_dienst) == 1


def test_report_standardname(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["report"]) == 0
    files = list(tmp_path.glob("tapesmith-bericht-*.zip"))
    assert len(files) == 1
    assert "Bericht gespeichert:" in capsys.readouterr().out


def test_report_mit_status(tmp_path, capsys, monkeypatch):
    status = {"view": {"title": "Tapesmith: verbunden", "detail": ""}, "queue": {"jobs": [{"id": 1}]}}
    monkeypatch.setattr(report_cmd, "STATUS_LOADER", lambda cfg: status)
    target = tmp_path / "b.zip"
    assert cli.main(["report", "--out", str(target)]) == 0
    with zipfile.ZipFile(target) as zf:
        text = zf.read("bericht.txt").decode("utf-8")
    assert "Tapesmith: verbunden" in text
    assert "Warteschlange: 1 Auftrag" in text


def test_daemon_status_ohne_dienst_ist_none():
    def refuse(**kw):
        raise OSError("kein Dienst")

    assert report_cmd.daemon_status({}, connector=refuse) is None
