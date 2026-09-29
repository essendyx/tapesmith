"""Tests für die Band-Eignung (tape.suitability)."""

import pytest

from tapesmith.tape import suitability
from tapesmith.tape.profiles import find_tape


def test_is_suitable_leer_ist_immer_geeignet():
    tape = find_tape("schwarz-weiss")
    assert suitability.is_suitable(tape, []) is True


def test_is_suitable_material():
    papier = find_tape("schwarz-weiss-papier")
    kunststoff = find_tape("schwarz-weiss")
    assert suitability.is_suitable(papier, ["material:kunststoff"]) is False
    assert suitability.is_suitable(kunststoff, ["material:kunststoff"]) is True


def test_is_suitable_by_id():
    tape = find_tape("schwarz-weiss")
    assert suitability.is_suitable(tape, ["schwarz-weiss"]) is True
    assert suitability.is_suitable(tape, ["weiss-schwarz"]) is False


def test_is_suitable_dunkel_hell():
    dunkel = find_tape("weiss-schwarz")
    hell = find_tape("schwarz-weiss")
    assert suitability.is_suitable(dunkel, ["dunkel"]) is True
    assert suitability.is_suitable(hell, ["dunkel"]) is False
    assert suitability.is_suitable(hell, ["hell"]) is True


def test_is_suitable_transparent():
    transparent = find_tape("schwarz-transparent")
    normal = find_tape("schwarz-weiss")
    assert suitability.is_suitable(transparent, ["transparent"]) is True
    assert suitability.is_suitable(normal, ["transparent"]) is False


def test_suitability_reason_beispieltext():
    papier = find_tape("schwarz-weiss-papier")
    reason = suitability.suitability_reason("gefriergut", papier, ["material:kunststoff"])
    assert reason == (
        "Vorlage 'gefriergut' ist für Kunststoffband gedacht, eingelegt: Schwarz auf Weiß (Papier)")


def test_suitability_reason_none_wenn_geeignet():
    tape = find_tape("schwarz-weiss")
    assert suitability.suitability_reason("x", tape, ["material:kunststoff"]) is None
    assert suitability.suitability_reason("x", tape, []) is None


def test_suitability_reason_mehrere_mit_oder():
    papier = find_tape("schwarz-weiss-papier")
    reason = suitability.suitability_reason("x", papier, ["transparent", "dunkel"])
    assert reason == "Vorlage 'x' ist für transparentes Band oder dunkles Band gedacht, eingelegt: Schwarz auf Weiß (Papier)"


def test_validate_allowed_ok():
    suitability.validate_allowed(["material:kunststoff", "transparent", "dunkel", "hell", "schwarz-weiss"])


def test_validate_allowed_unbekanntes_material_wirft():
    with pytest.raises(ValueError):
        suitability.validate_allowed(["material:holz"])


def test_validate_allowed_unbekannte_id_wirft():
    with pytest.raises(ValueError):
        suitability.validate_allowed(["gibtsnicht"])
