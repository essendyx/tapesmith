"""Tests für 'tapesmith tape' (CLI-Plugin)."""

import json

from tapesmith import paths
from tapesmith.cli import main


def test_tape_list_markiert_aktuelles(capsys):
    assert main(["tape", "list"]) == 0
    out = capsys.readouterr().out
    lines = [l for l in out.splitlines() if "schwarz-weiss" in l and "papier" not in l]
    assert lines
    assert lines[0].startswith("*")


def test_tape_set_speichert_in_config(capsys):
    assert main(["tape", "set", "weiss-schwarz"]) == 0
    data = json.loads(paths.config_path().read_text(encoding="utf-8"))
    assert data["tape"]["current"] == "weiss-schwarz"

    out = capsys.readouterr().out
    assert main(["tape", "list"]) == 0
    out2 = capsys.readouterr().out
    current_line = next(l for l in out2.splitlines() if l.startswith("*"))
    assert "weiss-schwarz" in current_line


def test_tape_set_unbekannt_exit_1(capsys):
    assert main(["tape", "set", "gibtsnicht"]) == 1
    assert "unbekannt" in capsys.readouterr().err


def test_tape_new_roll_und_roll(capsys):
    assert main(["tape", "new-roll"]) == 0
    out = capsys.readouterr().out
    assert "noch ca. 4,0 m" in out

    assert main(["tape", "roll"]) == 0
    out2 = capsys.readouterr().out
    assert "noch ca. 4,0 m" in out2


def test_tape_new_roll_mit_laenge(capsys):
    assert main(["tape", "new-roll", "--length-m", "8"]) == 0
    out = capsys.readouterr().out
    assert "noch ca. 8,0 m" in out


def test_tape_empty_gibt_faktor_aus(capsys):
    assert main(["tape", "new-roll"]) == 0
    capsys.readouterr()
    assert main(["tape", "empty", "--at-m", "3.9"]) == 0
    out = capsys.readouterr().out
    assert "Faktor gelernt:" in out
    assert "," in out  # Dezimalkomma statt Punkt
