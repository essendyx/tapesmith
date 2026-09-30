"""CLI-Integration `tapesmith garantie`: suche/print. Kein echtes Netz: TRANSPORT ersetzt."""

from tapesmith.cli import main
from tapesmith.cli_cmds import garantie as garantie_cmd

from homelab_fakes import load_json, mock_transport, token_file, write_homelab
import pytest

# Integrationen im Produkt ohne Standardadressen: Tests nutzen neutrale Testadressen.
pytestmark = pytest.mark.usefixtures("homelab_test_defaults")

ROUTES = {
    "GET /api/documents/": load_json("paperless/documents-search.json"),
    "GET /api/documents/17/": load_json("paperless/document-17.json"),
    "GET /api/correspondents/": load_json("paperless/correspondents.json"),
    "GET /api/custom_fields/": load_json("paperless/custom_fields.json"),
}


def _setup(tmp_path, monkeypatch):
    write_homelab({"paperless": {"token_ref": token_file(tmp_path, "paperless")}})
    monkeypatch.setattr(garantie_cmd, "TRANSPORT", mock_transport(ROUTES))


def test_suche_zeigt_tabelle(app_home, tmp_path, monkeypatch, capsys):
    _setup(tmp_path, monkeypatch)
    code = main(["garantie", "suche", "Rechnung"])
    out = capsys.readouterr().out
    assert code == 0
    assert "Kaffeemaschine" in out
    assert "Wasserkocher" in out


def test_print_preview_schreibt_datei_und_zeigt_garantie_bis(app_home, tmp_path, monkeypatch, capsys):
    _setup(tmp_path, monkeypatch)
    preview = tmp_path / "g.png"
    code = main(["garantie", "print", "17", "--preview", str(preview)])
    out = capsys.readouterr().out
    assert code == 0
    assert preview.is_file()
    assert "Garantie bis 28.02.2026" in out
    assert "QR enthält die lange Paperless-Adresse" in out
