"""CLI-Befehl `p12 ka` (neu, list, reserviert, verkauft, frei, print)."""

import json

from homelab_fakes import missing_refs, write_homelab
from tapesmith import cli
from tapesmith.cli_cmds import base as base_cmd


def test_neu_gibt_id_aus(app_home, capsys):
    code = cli.main(["ka", "neu", "Monitorarm", "--preis", "25 €", "--anzeige",
                     "https://example.org/a/1"])
    out = capsys.readouterr().out
    assert code == 0
    assert "KA-001" in out


def test_reserviert_mit_print_erzeugt_vorschau(app_home, tmp_path, capsys):
    assert cli.main(["ka", "neu", "Monitorarm"]) == 0
    capsys.readouterr()

    preview = tmp_path / "r.png"
    code = cli.main(["ka", "reserviert", "KA-001", "Hubert", "--bis", "30.09.2026",
                     "--print", "--preview", str(preview)])
    out = capsys.readouterr().out
    assert code == 0
    assert preview.is_file()
    assert "KA-001" in out


def test_list_status_filter_zeigt_namen(app_home, capsys):
    assert cli.main(["ka", "neu", "Monitorarm"]) == 0
    capsys.readouterr()
    assert cli.main(["ka", "reserviert", "KA-001", "Hubert", "--bis", "30.09.2026"]) == 0
    capsys.readouterr()

    code = cli.main(["ka", "list", "--status", "reserviert"])
    out = capsys.readouterr().out
    assert code == 0
    assert "Hubert" in out


def test_list_json(app_home, capsys):
    assert cli.main(["ka", "neu", "Monitorarm"]) == 0
    capsys.readouterr()

    code = cli.main(["ka", "list", "--json"])
    out = capsys.readouterr().out
    assert code == 0
    data = json.loads(out)
    assert data[0]["id"] == "KA-001"
    assert data[0]["titel"] == "Monitorarm"


def test_print_artikel_ohne_flag_schreibt_vorschau(app_home, tmp_path, capsys):
    assert cli.main(["ka", "neu", "Monitorarm", "--anzeige", "https://example.org/a/1"]) == 0
    capsys.readouterr()

    preview = tmp_path / "a.png"
    code = cli.main(["ka", "print", "KA-001", "--preview", str(preview)])
    assert code == 0
    assert preview.is_file()


def test_print_reserviert_flag(app_home, tmp_path, capsys):
    assert cli.main(["ka", "neu", "Monitorarm"]) == 0
    capsys.readouterr()
    assert cli.main(["ka", "reserviert", "KA-001", "Hubert", "--bis", "30.09.2026"]) == 0
    capsys.readouterr()

    preview = tmp_path / "r2.png"
    code = cli.main(["ka", "print", "KA-001", "--reserviert", "--preview", str(preview)])
    assert code == 0
    assert preview.is_file()


def test_neu_mit_print_und_preview_ohne_attributeerror(app_home, tmp_path, capsys):
    """`ka neu` registriert nur `add_print_options` (kein --dry-run/--contact-sheet);
    `--print --preview` darf trotzdem nicht mit AttributeError scheitern."""
    preview = tmp_path / "n.png"
    code = cli.main(["ka", "neu", "Test", "--anzeige", "https://example.org/x", "--print",
                     "--preview", str(preview)])
    assert code == 0
    assert preview.is_file()


def test_verkauft_ohne_datum_nutzt_heute(app_home, capsys):
    assert cli.main(["ka", "neu", "Monitorarm"]) == 0
    capsys.readouterr()
    code = cli.main(["ka", "verkauft", "KA-001", "Hubert"])
    out = capsys.readouterr().out
    assert code == 0
    assert "verkauft" in out


def test_frei_gibt_artikel_wieder_frei(app_home, capsys):
    assert cli.main(["ka", "neu", "Monitorarm"]) == 0
    capsys.readouterr()
    assert cli.main(["ka", "reserviert", "KA-001", "Hubert", "--bis", "30.09.2026"]) == 0
    capsys.readouterr()

    code = cli.main(["ka", "frei", "KA-001"])
    out = capsys.readouterr().out
    assert code == 0
    assert "verfügbar" in out


def test_ungueltiger_uebergang_ist_exit_1(app_home, capsys):
    assert cli.main(["ka", "neu", "Monitorarm"]) == 0
    capsys.readouterr()
    assert cli.main(["ka", "verkauft", "KA-001", "Hubert"]) == 0
    capsys.readouterr()

    code = cli.main(["ka", "reserviert", "KA-001", "Anna", "--bis", "30.09.2026"])
    err = capsys.readouterr().err
    assert code == 1
    assert "verkauft" in err


def test_unbekannte_id_bei_print_ist_exit_1(app_home, capsys):
    code = cli.main(["ka", "print", "KA-999"])
    err = capsys.readouterr().err
    assert code == 1
    assert "KA-999" in err


# ---------------------------------------------------------------- ka neu --print: kein halber Zustand


def _kein_druck(monkeypatch):
    def verboten(*args, **kwargs):
        raise AssertionError("Test darf nicht drucken")

    monkeypatch.setattr(base_cmd, "_print", verboten)


def test_neu_print_preview_ohne_kurzlink_token(app_home, tmp_path, monkeypatch, capsys):
    """Kurz-Link-Dienst eingerichtet, Token fehlt: die Vorschau braucht weder Netz noch Token."""
    data = missing_refs(tmp_path)
    data["shortlink"]["base_url"] = "https://k.example"
    write_homelab(data)
    _kein_druck(monkeypatch)
    preview = tmp_path / "k.png"
    code = cli.main(["ka", "neu", "Monitor", "--print", "--preview", str(preview)])
    assert code == 0
    assert preview.is_file()
    assert "KA-001" in capsys.readouterr().out


def test_neu_print_ohne_link_legt_nichts_an(app_home, tmp_path, monkeypatch, capsys):
    """Ohne Anzeige und ohne Kurz-Link-Dienst lässt sich kein Etikett erzeugen: keine Nummer, kein Artikel."""
    _kein_druck(monkeypatch)
    code = cli.main(["ka", "neu", "Monitor", "--print", "--preview", str(tmp_path / "x.png")])
    captured = capsys.readouterr()
    assert code == 1
    assert "Anzeigen-Adresse" in captured.err
    assert "KA-001" not in captured.out
    assert not (tmp_path / "x.png").exists()

    assert cli.main(["ka", "list", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == []
    assert cli.main(["ka", "neu", "Zweiter"]) == 0
    assert "KA-001" in capsys.readouterr().out


def test_neu_print_fehler_beim_kurzlink_rollt_zurueck(app_home, tmp_path, monkeypatch, capsys):
    """Echter Druck, Kurz-Link-Token fehlt: Artikel wird zurückgenommen, die Nummer verworfen."""
    data = missing_refs(tmp_path)
    data["shortlink"]["base_url"] = "https://k.example"
    write_homelab(data)
    _kein_druck(monkeypatch)
    code = cli.main(["ka", "neu", "Monitor", "--print"])
    captured = capsys.readouterr()
    assert code != 0
    assert "zurückgenommen" in captured.err

    assert cli.main(["ka", "list", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == []
    ranges = json.loads((app_home / "numbering" / "ranges.json").read_text(encoding="utf-8")) \
        if (app_home / "numbering" / "ranges.json").exists() else None
    if ranges is not None:
        assert [v["number"] for v in ranges["ka"]["voided"]] == ["KA-001"]
