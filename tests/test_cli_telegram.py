"""`p12 telegram status|test`, Versand nur über einen Fake-Poster."""

from __future__ import annotations

import json

from tapesmith import cli, paths
from tapesmith.cli_cmds import telegram as tg_cmd

TOKEN = "123:abc"


class _Resp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {"ok": True}

    def json(self):
        return self._payload


def _write_config(tmp_path, **tg) -> None:
    token_file = tmp_path / "t.txt"
    token_file.write_text(f"BOT_TOKEN={TOKEN}\n", encoding="utf-8")
    section = {"token_ref": f"file:{token_file}"}
    section.update(tg)
    path = paths.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"telegram": section}), encoding="utf-8")


def test_status_aus_ohne_chat_id(tmp_path, capsys):
    _write_config(tmp_path)
    assert cli.main(["telegram", "status"]) == 0
    out = capsys.readouterr().out
    assert "aus" in out
    assert "Chat-ID: fehlt" in out
    assert f"Datei {tmp_path / 't.txt'}" in out
    assert "vorhanden" in out
    assert "Ruhezeit: 22:00-07:00" in out
    assert TOKEN not in out


def test_status_an_mit_chat_id(tmp_path, capsys):
    _write_config(tmp_path, enabled=True, chat_id="4711", quiet_hours=None, roll_low_m=0.5)
    assert cli.main(["telegram", "status"]) == 0
    out = capsys.readouterr().out
    assert "Telegram-Meldungen: an" in out
    assert "Chat-ID: gesetzt" in out
    assert "Ruhezeit: keine" in out
    assert "0,5 m" in out
    assert TOKEN not in out


def test_test_gesendet(tmp_path, monkeypatch, capsys):
    _write_config(tmp_path, chat_id="4711")
    calls = []

    def post(url, json=None, timeout=None):
        calls.append((url, json))
        return _Resp()

    monkeypatch.setattr(tg_cmd, "HTTP_POST", post)
    assert cli.main(["telegram", "test"]) == 0
    assert "Gesendet." in capsys.readouterr().out
    assert calls and f"bot{TOKEN}/" in calls[0][0]
    assert calls[0][1]["chat_id"] == "4711"


def test_test_fehler_ohne_token(tmp_path, monkeypatch, capsys):
    _write_config(tmp_path, chat_id="4711")
    monkeypatch.setattr(tg_cmd, "HTTP_POST",
                        lambda url, json=None, timeout=None: _Resp(401, {"ok": False, "description": "Unauthorized"}))
    assert cli.main(["telegram", "test"]) == 1
    captured = capsys.readouterr()
    text = captured.out + captured.err
    assert "Fehler: " in text
    assert "Unauthorized" in text
    assert TOKEN not in text


def test_test_ohne_chat_id(tmp_path, monkeypatch, capsys):
    _write_config(tmp_path)
    monkeypatch.setattr(tg_cmd, "HTTP_POST", lambda *a, **k: _Resp())
    assert cli.main(["telegram", "test"]) == 1
    captured = capsys.readouterr()
    assert "Chat-ID fehlt" in captured.out + captured.err
