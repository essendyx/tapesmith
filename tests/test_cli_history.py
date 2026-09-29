import json

from PIL import Image

from tapesmith import cli, paths
from tapesmith.history import HistoryStore
from tapesmith.jobs import JobMeta


def _store():
    return HistoryStore(paths.history_db_path())


def test_history_empty_reports_empty(app_home, capsys):
    assert cli.main(["history"]) == 0
    assert "Verlauf ist leer" in capsys.readouterr().out


def test_history_lists_entries(app_home, capsys):
    with _store() as store:
        store.record(JobMeta(title="Datenträger SN274913"), landscape=Image.new("1", (40, 30), 255),
                     head=None, length_mm=10.0, tape_mm=20.0)
        store.record(JobMeta(title="Zweites Label"), landscape=Image.new("1", (40, 30), 255),
                     head=None, length_mm=10.0, tape_mm=20.0)

    assert cli.main(["history"]) == 0
    out = capsys.readouterr().out
    assert "Datenträger SN274913" in out
    assert "Zweites Label" in out


def test_history_query_filters_entries(app_home, capsys):
    with _store() as store:
        store.record(JobMeta(title="Datenträger SN274913"), landscape=Image.new("1", (40, 30), 255),
                     head=None, length_mm=10.0, tape_mm=20.0)
        store.record(JobMeta(title="Zweites Label"), landscape=Image.new("1", (40, 30), 255),
                     head=None, length_mm=10.0, tape_mm=20.0)

    assert cli.main(["history", "274913"]) == 0
    out = capsys.readouterr().out
    assert "Datenträger SN274913" in out
    assert "Zweites Label" not in out


def test_history_no_matches_message(app_home, capsys):
    with _store() as store:
        store.record(JobMeta(title="Etwas"), landscape=Image.new("1", (40, 30), 255),
                     head=None, length_mm=10.0, tape_mm=20.0)

    assert cli.main(["history", "999999"]) == 0
    assert "Keine Treffer für '999999'" in capsys.readouterr().out


def test_history_json_output(app_home, capsys):
    with _store() as store:
        store.record(JobMeta(title="Json-Eintrag"), landscape=Image.new("1", (40, 30), 255),
                      head=None, length_mm=10.0, tape_mm=20.0)

    assert cli.main(["history", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert isinstance(data, list)
    assert data[0]["title"] == "Json-Eintrag"


def test_history_show_writes_thumbnail(app_home, capsys, tmp_path):
    with _store() as store:
        entry_id = store.record(JobMeta(title="Mit Bild"), landscape=Image.new("1", (40, 30), 255),
                                 head=None, length_mm=10.0, tape_mm=20.0)

    thumb_path = tmp_path / "thumb.png"
    assert cli.main(["history", "--show", str(entry_id), "--thumbnail", str(thumb_path)]) == 0
    out = capsys.readouterr().out
    assert "Mit Bild" in out
    assert thumb_path.exists()


def test_history_show_unknown_id_is_exit_1(app_home, capsys):
    assert cli.main(["history", "--show", "999"]) == 1
    assert capsys.readouterr().err.strip() == "Fehler: Verlaufseintrag 999 gibt es nicht"


def test_history_limit_option(app_home, capsys):
    with _store() as store:
        for i in range(5):
            store.record(JobMeta(title=f"Label {i}"), landscape=Image.new("1", (40, 30), 255),
                         head=None, length_mm=10.0, tape_mm=20.0)

    assert cli.main(["history", "--limit", "2"]) == 0
    out = capsys.readouterr().out
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert len(lines) == 2
