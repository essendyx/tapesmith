"""Tests für Bandprofile (tape.profiles)."""

import json

import pytest

from tapesmith import paths
from tapesmith.tape import profiles

TABLE_IDS = {
    "schwarz-weiss", "schwarz-weiss-papier", "schwarz-transparent", "weiss-schwarz",
    "gold-schwarz", "schwarz-gold", "schwarz-silber", "schwarz-gelb", "schwarz-blau",
    "schwarz-rosa",
}


def test_builtin_tapes_enthaelt_alle_tabellen_ids():
    ids = {t.id for t in profiles.builtin_tapes()}
    assert TABLE_IDS <= ids


def test_dark_und_effective_code_mode():
    weiss_schwarz = profiles.find_tape("weiss-schwarz")
    assert weiss_schwarz.dark is True
    assert weiss_schwarz.effective_code_mode == "invert"

    schwarz_weiss = profiles.find_tape("schwarz-weiss")
    assert schwarz_weiss.dark is False
    assert schwarz_weiss.effective_code_mode == "normal"


def test_explicit_code_mode_overrides_automatic():
    tape = profiles.TapeProfile(id="x", name="x", background=(255, 255, 255), ink=(0, 0, 0),
                                 code_mode="warn")
    assert tape.effective_code_mode == "warn"


def test_find_tape_unbekannt_wirft_mit_vorhandenen_ids():
    with pytest.raises(ValueError, match="unbekannt"):
        profiles.find_tape("gibtsnicht")


def test_user_tapes_overrides_and_adds(app_home):
    user_path = profiles.user_tapes_path()
    user_path.write_text(json.dumps([
        {"id": "schwarz-weiss", "name": "Anderer Name", "background": [255, 255, 255], "ink": [0, 0, 0]},
        {"id": "mein-band", "name": "Mein Band", "background": [10, 20, 30], "ink": [200, 200, 200]},
    ]), encoding="utf-8")

    tapes = profiles.list_tapes()
    by_id = {t.id: t for t in tapes}
    assert by_id["schwarz-weiss"].name == "Anderer Name"
    assert by_id["mein-band"].name == "Mein Band"
    # Reihenfolge: eingebaut zuerst, neue danach
    assert [t.id for t in tapes].index("mein-band") > [t.id for t in tapes].index("schwarz-weiss")


def test_user_tapes_invalid_color_raises_with_filename(app_home):
    user_path = profiles.user_tapes_path()
    user_path.write_text(json.dumps([
        {"id": "kaputt", "name": "Kaputt", "background": [999, 0, 0], "ink": [0, 0, 0]},
    ]), encoding="utf-8")

    with pytest.raises(ValueError, match="tapes.json"):
        profiles.list_tapes()


def test_current_tape_defaults_and_lookup():
    assert profiles.current_tape({}).id == "schwarz-weiss"
    assert profiles.current_tape({"tape": {"current": "weiss-schwarz"}}).id == "weiss-schwarz"


def test_current_tape_unknown_id_falls_back_to_default():
    assert profiles.current_tape({"tape": {"current": "nope"}}).id == "schwarz-weiss"


@pytest.mark.parametrize("field,value", [
    ("material", "holz"),
    ("code_mode", "kaputt"),
    ("density", 0),
    ("density", 16),
])
def test_invalid_field_raises(app_home, field, value):
    user_path = profiles.user_tapes_path()
    entry = {"id": "x", "name": "x", "background": [255, 255, 255], "ink": [0, 0, 0], field: value}
    user_path.write_text(json.dumps([entry]), encoding="utf-8")
    with pytest.raises(ValueError):
        profiles.list_tapes()
