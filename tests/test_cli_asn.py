"""CLI-Integration `p12 asn`: next/reserve/void. Kein echtes Netz: `TRANSPORT` ersetzt."""

from tapesmith import cli
from tapesmith.cli_cmds import asn as asn_cmd

from homelab_fakes import load_json, mock_transport, token_file, write_homelab
import pytest

# Integrationen im Produkt ohne Standardadressen: Tests nutzen neutrale Testadressen.
pytestmark = pytest.mark.usefixtures("homelab_test_defaults")


def _setup(tmp_path, monkeypatch, routes=None):
    write_homelab({"paperless": {"token_ref": token_file(tmp_path, "paperless")}})
    monkeypatch.setattr(asn_cmd, "TRANSPORT",
                        mock_transport(routes or {"GET /api/documents/next_asn/": load_json("paperless/next_asn.json")}))


def test_next_gibt_hinweis_aus(app_home, tmp_path, monkeypatch, capsys):
    _setup(tmp_path, monkeypatch)
    code = cli.main(["asn", "next"])
    out = capsys.readouterr().out
    assert code == 0
    assert "42" in out
    assert "einscannen" in out


def test_reserve_dry_run_reserviert_nicht(app_home, tmp_path, monkeypatch, capsys):
    _setup(tmp_path, monkeypatch)
    code = cli.main(["asn", "reserve", "2", "--print", "--dry-run"])
    out = capsys.readouterr().out
    assert code == 0
    lines = [line for line in out.splitlines() if line.strip()]
    assert lines == ["ASN00042", "ASN00043"]

    # nichts reserviert: der Nummernkreis ist noch nicht angelegt
    code2 = cli.main(["asn", "next"])
    out2 = capsys.readouterr().out
    assert "noch kein Nummernkreis angelegt" in out2


def test_reserve_dry_run_ohne_print_reserviert_nicht(app_home, tmp_path, monkeypatch, capsys):
    _setup(tmp_path, monkeypatch)
    code = cli.main(["asn", "reserve", "2", "--dry-run"])
    out = capsys.readouterr().out
    assert code == 0
    lines = [line for line in out.splitlines() if line.strip()]
    assert lines == ["ASN00042", "ASN00043"]

    cli.main(["asn", "next"])
    assert "noch kein Nummernkreis angelegt" in capsys.readouterr().out


def test_reserve_ohne_print_reserviert_und_gibt_zwei_zeilen_aus(app_home, tmp_path, monkeypatch, capsys):
    _setup(tmp_path, monkeypatch)
    code = cli.main(["asn", "reserve", "2"])
    out = capsys.readouterr().out
    assert code == 0
    lines = [line for line in out.splitlines() if line.strip()]
    assert lines == ["ASN00042", "ASN00043"]


def test_reserve_print_preview_schreibt_vorschau(app_home, tmp_path, monkeypatch, capsys):
    _setup(tmp_path, monkeypatch)
    preview = tmp_path / "p.png"
    code = cli.main(["asn", "reserve", "2", "--print", "--preview", str(preview)])
    assert code == 0
    assert preview.is_file()


def test_void_verwirft_reservierte_nummer(app_home, tmp_path, monkeypatch, capsys):
    _setup(tmp_path, monkeypatch)
    cli.main(["asn", "reserve", "1"])
    capsys.readouterr()
    code = cli.main(["asn", "void", "ASN00042", "--grund", "Fehldruck"])
    out = capsys.readouterr().out
    assert code == 0
    assert "verworfen" in out
