"""CLI-Integration `tapesmith batch`: Import/Serie, Trockenlauf, Kontaktabzug, Druck."""

import json

from tapesmith import cli, paths
from tapesmith.history import HistoryStore
from tapesmith.templates.store import user_dir

CSV = "host;slot;sn\npmx10;SSD-1;274913\npmx20;SSD-2;274914\npmx10;SSD-3;274915\n"

BOX_TEMPLATE = {
    "schema_version": 2, "name": "box-batch-test", "description": "",
    "fields": [{"id": "box", "label": "Box", "type": "input", "required": True}],
    "layout": {"lines": ["{box}"]},
}

EINZELFELD_TEMPLATE = {
    "schema_version": 2, "name": "einzelfeld-batch-test", "description": "",
    "fields": [{"id": "host", "label": "Host", "type": "input", "required": True}],
    "layout": {"lines": ["{host}"]},
}


def _write(data: dict) -> None:
    (user_dir() / f"{data['name']}.tapesmith.json").write_text(json.dumps(data), encoding="utf-8")


def _counters_path():
    return paths.app_dir() / "counters.json"


# 8. CSV -> dry-run + Kontaktabzug, keine Zähler/Verlauf --------------------------------------

def test_dry_run_csv_writes_summary_and_contact_sheet(app_home, tmp_path, capsys):
    csv_path = tmp_path / "x.csv"
    csv_path.write_text(CSV, encoding="utf-8")
    sheet = tmp_path / "ks.png"

    code = cli.main(["batch", "datentraeger", "--data", str(csv_path), "--dry-run",
                     "--contact-sheet", str(sheet)])
    out = capsys.readouterr().out
    assert code == 0
    assert "3 Labels" in out
    assert sheet.is_file()
    assert not _counters_path().exists()
    with HistoryStore(paths.history_db_path()) as store:
        assert store.last() is None


# 9. --rows / --filter ------------------------------------------------------------------------

def test_rows_selection(app_home, tmp_path, capsys):
    csv_path = tmp_path / "x.csv"
    csv_path.write_text(CSV, encoding="utf-8")
    code = cli.main(["batch", "datentraeger", "--data", str(csv_path), "--rows", "1,3", "--dry-run"])
    assert code == 0
    assert "2 Labels" in capsys.readouterr().out


def test_filter_selection(app_home, tmp_path, capsys):
    csv_path = tmp_path / "x.csv"
    csv_path.write_text(CSV, encoding="utf-8")
    code = cli.main(["batch", "datentraeger", "--data", str(csv_path), "--filter", "pmx20", "--dry-run"])
    assert code == 0
    assert "1 Labels" in capsys.readouterr().out


# 10. --series -------------------------------------------------------------------------------

def test_series_simple_with_fixed_value(app_home, capsys):
    code = cli.main(["batch", "datentraeger", "--series", "slot=1..4", "--set", "sn=274913", "--dry-run"])
    assert code == 0
    assert "4 Labels" in capsys.readouterr().out


def test_series_nested_box(app_home, capsys):
    _write(BOX_TEMPLATE)
    code = cli.main(["batch", "box-batch-test", "--series", "box=A1..2x3", "--dry-run"])
    assert code == 0
    assert "6 Labels" in capsys.readouterr().out


# 11. Pflichtfeld nicht zugeordnet --------------------------------------------------------------

def test_required_field_unmapped_is_exit_6(app_home, tmp_path, capsys):
    csv_path = tmp_path / "ohne_sn.csv"
    csv_path.write_text("host;slot\npmx10;SSD-1\n", encoding="utf-8")
    code = cli.main(["batch", "datentraeger", "--data", str(csv_path), "--dry-run"])
    err = capsys.readouterr().err
    assert code == 6
    assert "sn" in err.casefold() or "seriennummer" in err.casefold()


# 12. Druck (file transport) mit Kette -------------------------------------------------------

def test_print_via_file_transport_records_history(app_home, tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "SLEEP", lambda s: None)
    csv_path = tmp_path / "x.csv"
    csv_path.write_text(CSV, encoding="utf-8")
    job = tmp_path / "job.bin"

    code = cli.main(["--transport", f"file:{job}", "batch", "datentraeger", "--data", str(csv_path),
                     "--chain", "--yes"])
    assert code == 0
    assert job.exists() and job.stat().st_size > 0
    with HistoryStore(paths.history_db_path()) as store:
        entry = store.last()
        assert entry is not None
        assert entry.title.startswith("Serie (3): ")


# 13. --lines - -------------------------------------------------------------------------------

def test_lines_from_stdin(app_home, monkeypatch, capsys):
    _write(EINZELFELD_TEMPLATE)
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO("a\nb\nc\n"))
    code = cli.main(["batch", "einzelfeld-batch-test", "--lines", "-", "--dry-run"])
    assert code == 0
    assert "3 Labels" in capsys.readouterr().out


# 14. parse_series_arg-Fehler -----------------------------------------------------------------

def test_series_parse_error_is_exit_1_with_example(app_home, capsys):
    code = cli.main(["batch", "datentraeger", "--series", "slot=abc", "--dry-run"])
    err = capsys.readouterr().err
    assert code == 1
    assert "Beispiel" in err
