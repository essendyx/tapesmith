"""CLI-Befehl `p12 asset`."""

import json

from tapesmith import cli, paths
from tapesmith.cli_cmds import asset as asset_cmd
from tapesmith.integrations import assets as assets_mod


def test_neu_creates_two_numbers(app_home, capsys):
    code = cli.main(["asset", "neu", "2", "--bezeichnung", "Test"])
    out = capsys.readouterr().out
    assert code == 0
    assert "HL-0001" in out
    assert "HL-0002" in out


def test_neu_dry_run_with_print_does_not_reserve(app_home, capsys):
    code = cli.main(["asset", "neu", "1", "--print", "--dry-run"])
    capsys.readouterr()
    assert code == 0
    assert not (paths.app_dir() / "nummernkreise.json").exists()


def test_neu_dry_run_shows_preview_without_side_effects(app_home, capsys):
    code = cli.main(["asset", "neu", "3", "--dry-run"])
    out = capsys.readouterr().out
    assert code == 0
    assert out.splitlines() == ["HL-0001", "HL-0002", "HL-0003"]
    assert not (paths.app_dir() / "nummernkreise.json").exists()


def test_print_with_preview_creates_file(app_home, tmp_path, capsys):
    cli.main(["asset", "neu", "1", "--bezeichnung", "Patchkabel", "--ziel", "https://x.example/a"])
    capsys.readouterr()
    preview = tmp_path / "p.png"
    code = cli.main(["asset", "print", "HL-0001", "--preview", str(preview)])
    capsys.readouterr()
    assert code == 0
    assert preview.is_file()


def test_print_unknown_id_is_exit_1(app_home, capsys):
    code = cli.main(["asset", "print", "HL-9999", "--dry-run"])
    err = capsys.readouterr().err
    assert code == 1
    assert "HL-9999" in err


def test_void_sets_status(app_home, capsys):
    cli.main(["asset", "neu", "1"])
    capsys.readouterr()
    code = cli.main(["asset", "void", "HL-0001", "--grund", "Fehldruck"])
    out = capsys.readouterr().out
    assert code == 0
    assert "HL-0001" in out


def test_list_json(app_home, capsys):
    cli.main(["asset", "neu", "2", "--bezeichnung", "Test"])
    capsys.readouterr()
    code = cli.main(["asset", "list", "--json"])
    data = json.loads(capsys.readouterr().out)
    assert code == 0
    assert [a["id"] for a in data] == ["HL-0001", "HL-0002"]


def test_show_unknown_is_exit_1(app_home, capsys):
    code = cli.main(["asset", "show", "HL-9999"])
    err = capsys.readouterr().err
    assert code == 1
    assert "HL-9999" in err


def test_set_updates_field(app_home, capsys):
    cli.main(["asset", "neu", "1"])
    capsys.readouterr()
    code = cli.main(["asset", "set", "HL-0001", "standort=Schrank 3"])
    out = capsys.readouterr().out
    assert code == 0
    assert "HL-0001" in out
    code = cli.main(["asset", "show", "HL-0001"])
    data = json.loads(capsys.readouterr().out)
    assert data["standort"] == "Schrank 3"


def test_import_existing_number(app_home, capsys):
    code = cli.main(["asset", "import", "HL-0500", "bezeichnung=Alt-Gerät"])
    out = capsys.readouterr().out
    assert code == 0
    assert "HL-0500" in out

    duplicate = cli.main(["asset", "import", "HL-0500"])
    err = capsys.readouterr().err
    assert duplicate == 1
    assert "existiert" in err


def test_export_writes_csv(app_home, tmp_path, capsys):
    cli.main(["asset", "neu", "1", "--bezeichnung", "Patchkabel"])
    capsys.readouterr()
    out_file = tmp_path / "export.csv"
    code = cli.main(["asset", "export", str(out_file)])
    capsys.readouterr()
    assert code == 0
    text = out_file.read_text(encoding="utf-8")
    assert text.startswith("﻿id;bezeichnung;")
    assert "HL-0001;Patchkabel" in text


def test_neu_print_preview_does_not_touch_shortlink(app_home, tmp_path, monkeypatch, capsys):
    from homelab_fakes import mock_transport, token_file, write_homelab

    write_homelab({"shortlink": {"base_url": "https://l.example.com",
                                 "token_ref": token_file(tmp_path, "sl")}})
    calls = []
    transport = mock_transport({"PUT /api/links/HL-0001": (201, {
        "id": "HL-0001", "target": "https://x.example/a", "note": "", "created": "", "updated": "",
        "hits": 0})}, calls=calls)
    monkeypatch.setattr(asset_cmd, "TRANSPORT", transport)

    preview = tmp_path / "p.png"
    code = cli.main(["asset", "neu", "1", "--ziel", "https://x.example/a", "--print",
                     "--preview", str(preview)])
    capsys.readouterr()
    assert code == 0
    assert preview.is_file()
    assert calls == []


def test_real_print_sets_link_but_keeps_existing_target(app_home, monkeypatch, capsys):
    from tapesmith.integrations import cliprint

    service = _shortlink_setup(app_home, monkeypatch)
    monkeypatch.setattr(cliprint, "emit_labels", lambda *a, **kw: True)
    cli.main(["asset", "neu", "2", "--bezeichnung", "NAS"])
    service.links["HL-0001"] = {"id": "HL-0001", "target": "https://ziel.example", "note": "",
                                "created": "", "updated": "", "hits": 0}
    code = cli.main(["asset", "print", "HL-0001", "HL-0002"])
    capsys.readouterr()
    assert code == 0
    assert service.links["HL-0001"]["target"] == "https://ziel.example"
    assert service.links["HL-0002"] == {"id": "HL-0002", "target": None, "note": "NAS",
                                        "created": "", "updated": "", "hits": 0}


def test_luhn_check_digit_asset_ids(app_home, capsys):
    cli.main(["homelab", "set", "assets.check_digit", "true"])
    capsys.readouterr()
    code = cli.main(["asset", "neu", "1"])
    out = capsys.readouterr().out.strip()
    assert code == 0
    assert assets_mod.verify_id(out, "HL-", check_digit=True)


# ---------- Vorschau und Trockenlauf ohne Kurz-Link-Schreibzugriff ----------

def _shortlink_setup(app_home, monkeypatch, *, token=True):
    from homelab_fakes import FakeShortlinkService, token_file, write_homelab
    from tapesmith.cli_cmds import kurz as kurz_cmd

    ref = token_file(app_home, "sl") if token else f"file:{app_home / 'fehlt'}"
    write_homelab({"shortlink": {"base_url": "https://l.example.com", "token_ref": ref}})
    service = FakeShortlinkService()
    monkeypatch.setattr(asset_cmd, "TRANSPORT", service.transport)
    monkeypatch.setattr(kurz_cmd, "TRANSPORT", service.transport)
    return service


def test_kurz_set_then_preview_keeps_target(app_home, tmp_path, monkeypatch, capsys):
    service = _shortlink_setup(app_home, monkeypatch)
    assert cli.main(["asset", "neu", "1", "--bezeichnung", "NAS"]) == 0
    assert cli.main(["kurz", "set", "HL-0001", "https://ziel.example"]) == 0
    preview = tmp_path / "a.png"
    assert cli.main(["asset", "print", "HL-0001", "--preview", str(preview)]) == 0
    assert preview.is_file()
    capsys.readouterr()
    assert cli.main(["kurz", "get", "HL-0001"]) == 0
    link = json.loads(capsys.readouterr().out)
    assert link["target"] == "https://ziel.example"
    assert service.links["HL-0001"]["target"] == "https://ziel.example"


def test_preview_and_dry_run_need_no_token_and_no_network(app_home, tmp_path, monkeypatch, capsys):
    service = _shortlink_setup(app_home, monkeypatch, token=False)
    assert cli.main(["asset", "neu", "1", "--bezeichnung", "NAS"]) == 0
    code_preview = cli.main(["asset", "print", "HL-0001", "--preview", str(tmp_path / "a.png")])
    code_dry = cli.main(["asset", "print", "HL-0001", "--dry-run"])
    err = capsys.readouterr().err
    assert (code_preview, code_dry) == (0, 0), err
    assert service.calls == []


def test_kurz_set_updates_local_asset_ziel(app_home, monkeypatch, capsys):
    _shortlink_setup(app_home, monkeypatch)
    cli.main(["asset", "neu", "1"])
    assert cli.main(["kurz", "set", "hl-0001", "https://ziel.example"]) == 0
    capsys.readouterr()
    with assets_mod.AssetStore() as store:
        assert store.get("HL-0001").ziel == "https://ziel.example"


def test_kurz_set_updates_local_ka_anzeige(app_home, monkeypatch, capsys):
    from tapesmith.integrations import kleinanzeigen as ka

    service = _shortlink_setup(app_home, monkeypatch)
    assert cli.main(["ka", "neu", "Monitorarm"]) == 0
    assert cli.main(["kurz", "set", "KA-001", "https://anzeige.example/1"]) == 0
    capsys.readouterr()
    with ka.KaStore() as store:
        assert store.get("KA-001").anzeige == "https://anzeige.example/1"
    assert service.links["KA-001"]["target"] == "https://anzeige.example/1"


def test_kurz_set_without_local_databases_creates_none(app_home, monkeypatch, capsys):
    from tapesmith.integrations import settings

    _shortlink_setup(app_home, monkeypatch)
    assert cli.main(["kurz", "set", "X1", "https://ziel.example"]) == 0
    capsys.readouterr()
    assert not (settings.data_dir() / "assets.sqlite3").exists()
    assert not (settings.data_dir() / "kleinanzeigen.sqlite3").exists()
