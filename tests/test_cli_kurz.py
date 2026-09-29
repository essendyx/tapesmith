"""CLI-Befehl `p12 kurz` (Client-Seite)."""

import json

from homelab_fakes import mock_transport, token_file, write_homelab
from tapesmith import cli
from tapesmith.cli_cmds import kurz as kurz_cmd


def _link(link_id="HL-7", target="https://x.example/a"):
    return {"id": link_id, "target": target, "note": "", "created": "2026-09-28T10:00:00",
            "updated": "2026-09-28T10:00:00", "hits": 0}


def test_url_without_network_or_token(app_home, capsys):
    write_homelab({"shortlink": {"base_url": "https://l.example.com"}})
    code = cli.main(["kurz", "url", "hl-7"])
    out = capsys.readouterr().out.strip()
    assert code == 0
    assert out == "HTTPS://L.EXAMPLE.COM/HL-7"


def test_url_not_configured_is_exit_1(app_home, capsys):
    code = cli.main(["kurz", "url", "hl-7"])
    err = capsys.readouterr().err
    assert code == 1
    assert "nicht eingerichtet" in err


def test_set_sends_put(app_home, tmp_path, monkeypatch, capsys):
    write_homelab({"shortlink": {"base_url": "https://l.example.com",
                                 "token_ref": token_file(tmp_path, "sl")}})
    calls = []
    monkeypatch.setattr(kurz_cmd, "TRANSPORT",
                        mock_transport({"PUT /api/links/HL-7": (201, _link())}, calls=calls))
    code = cli.main(["kurz", "set", "HL-7", "https://x.example.com"])
    out = capsys.readouterr().out
    assert code == 0
    assert "HL-7" in out
    assert calls[0].method == "PUT"
    assert json.loads(calls[0].content)["target"] == "https://x.example.com"


def test_set_dash_clears_target(app_home, tmp_path, monkeypatch, capsys):
    write_homelab({"shortlink": {"base_url": "https://l.example.com",
                                 "token_ref": token_file(tmp_path, "sl")}})
    calls = []
    monkeypatch.setattr(kurz_cmd, "TRANSPORT",
                        mock_transport({"PUT /api/links/HL-7": (201, _link(target=None))}, calls=calls))
    code = cli.main(["kurz", "set", "HL-7", "-"])
    capsys.readouterr()
    assert code == 0
    assert json.loads(calls[0].content)["target"] is None


def test_set_without_token_is_exit_1(app_home, capsys):
    write_homelab({"shortlink": {"base_url": "https://l.example.com",
                                 "token_ref": f"file:{app_home / 'no-token'}"}})
    code = cli.main(["kurz", "set", "HL-7", "https://x.example.com"])
    err = capsys.readouterr().err
    assert code == 1
    assert "Token fehlt" in err


def test_list_and_get(app_home, tmp_path, monkeypatch, capsys):
    write_homelab({"shortlink": {"base_url": "https://l.example.com",
                                 "token_ref": token_file(tmp_path, "sl")}})
    monkeypatch.setattr(kurz_cmd, "TRANSPORT", mock_transport({
        "GET /api/links": {"links": [_link()]},
        "GET /api/links/HL-7": _link(),
        "GET /api/links/NONE": (404, {"error": "x"}),
    }))
    assert cli.main(["kurz", "list"]) == 0
    assert "HL-7" in capsys.readouterr().out

    assert cli.main(["kurz", "get", "HL-7"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["id"] == "HL-7"

    assert cli.main(["kurz", "get", "NONE"]) == 1
    assert "NONE" in capsys.readouterr().err


def test_rm(app_home, tmp_path, monkeypatch, capsys):
    write_homelab({"shortlink": {"base_url": "https://l.example.com",
                                 "token_ref": token_file(tmp_path, "sl")}})
    monkeypatch.setattr(kurz_cmd, "TRANSPORT", mock_transport({
        "DELETE /api/links/HL-7": (204, None),
    }))
    assert cli.main(["kurz", "rm", "HL-7"]) == 0
    assert "Gelöscht" in capsys.readouterr().out
