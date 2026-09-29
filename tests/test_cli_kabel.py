"""CLI-Befehl `p12 kabel` (netbox, ids, register, pruefen)."""

from pathlib import Path

from homelab_fakes import write_homelab
from tapesmith import cli
from tapesmith.integrations import tia606
from tapesmith.numbering import numbering_dir, FILE_NAME
from tapesmith import config

DATA = Path(__file__).parent / "data" / "netbox" / "cables-export.csv"


def _numbering_path() -> Path:
    return numbering_dir(config.load_config()) / FILE_NAME


def test_kabel_in_help(capsys):
    try:
        cli.main(["--help"])
    except SystemExit:
        pass
    assert "kabel" in capsys.readouterr().out


def test_netbox_shows_table(capsys):
    write_homelab({})
    assert cli.main(["kabel", "netbox", str(DATA)]) == 0
    out = capsys.readouterr().out
    assert "K-100" in out
    assert "SW1" in out


def test_netbox_neue_ids_dry_run_assigns_no_numbers(capsys):
    write_homelab({})
    assert cli.main(["kabel", "netbox", str(DATA), "--neue-ids", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "neu 1" in out
    assert not _numbering_path().exists()


def test_ids_schema_three(capsys):
    write_homelab({})
    assert cli.main(["kabel", "ids", "--schema", "R1", "--units", "12", "--ports", "1-3"]) == 0
    out = capsys.readouterr().out.split()
    assert out == ["R1.U12:P01", "R1.U12:P02", "R1.U12:P03"]


def test_ids_frei_print_dry_run_reserves_nothing(capsys):
    write_homelab({})
    assert cli.main(["kabel", "ids", "--frei", "2", "--print", "--dry-run"]) == 0
    assert not _numbering_path().exists()


def test_pruefen_exit_codes(capsys):
    write_homelab({})
    assert cli.main(["kabel", "pruefen", "K-001"]) == 0
    tia606.KabelRegister().add([
        tia606.KabelEntry(id="K-001", quelle="", ziel="", kabeltyp="", quelle_import="manuell",
                          created="2026-09-28T10:00:00"),
    ])
    assert cli.main(["kabel", "pruefen", "K-001"]) == 1


def test_register_lists_entries(capsys):
    write_homelab({})
    tia606.KabelRegister().add([
        tia606.KabelEntry(id="K-001", quelle="SW1/P1", ziel="pmx10/eno1", kabeltyp="Cat6",
                          quelle_import="manuell", created="2026-09-28T10:00:00"),
    ])
    assert cli.main(["kabel", "register"]) == 0
    assert "K-001" in capsys.readouterr().out
