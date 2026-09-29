"""Tests für das Befehlsregister: unscharfe Suche, Aktivierung, Ausführung."""

import pytest

from tapesmith.commandreg import Command, CommandRegistry, fold


def _registry() -> CommandRegistry:
    reg = CommandRegistry()
    counters = {"ssd": 0, "reprint": 0, "tape": 0}
    reg.register(Command(id="vorlage.datentraeger", title="Neues SSD-/Datenträger-Etikett",
                          run=lambda: counters.__setitem__("ssd", counters["ssd"] + 1),
                          keywords=("ssd", "hdd", "platte"), group="Vorlagen"))
    reg.register(Command(id="druck.wieder", title="Letztes erneut drucken",
                          run=lambda: counters.__setitem__("reprint", counters["reprint"] + 1),
                          keywords=("wieder", "nochmal", "reprint"), group="Drucken"))
    reg.register(Command(id="band.waehlen", title="Bandprofil wählen",
                          run=lambda: counters.__setitem__("tape", counters["tape"] + 1),
                          keywords=("band", "tape"), group="Werkzeuge"))
    reg.register(Command(id="verlauf.geoeffnet", title="Geöffnet am", run=lambda: None,
                          group="Verlauf"))
    reg.register(Command(id="einstellungen", title="Einstellungen", run=lambda: None,
                          group="Werkzeuge"))
    return reg


# 1 ----------------------------------------------------------------------------

def test_search_keyword_exakt_liefert_passenden_befehl_zuerst():
    reg = _registry()
    assert reg.search("ssd")[0].id == "vorlage.datentraeger"
    assert reg.search("wieder")[0].id == "druck.wieder"
    assert reg.search("band")[0].id == "band.waehlen"


def test_search_findet_umlaute_ohne_ruecksicht_auf_schreibweise():
    reg = _registry()
    assert any(c.id == "verlauf.geoeffnet" for c in reg.search("geoeffnet"))
    assert any(c.id == "verlauf.geoeffnet" for c in reg.search("GEÖFF"))


def test_search_teilfolge_findet_titel():
    reg = _registry()
    assert any(c.id == "druck.wieder" for c in reg.search("ledr"))


def test_search_ohne_treffer_ist_leer():
    reg = _registry()
    assert reg.search("xyz") == []


# 2 ----------------------------------------------------------------------------

def test_deaktivierter_befehl_erscheint_nicht_und_run_wirft():
    reg = CommandRegistry()
    reg.register(Command(id="aus", title="Ausgeblendet", run=lambda: None, enabled=lambda: False))
    assert reg.search("ausgeblendet") == []
    assert reg.get("aus") not in reg.search("")
    with pytest.raises(ValueError, match="gerade nicht verfügbar"):
        reg.run("aus")


def test_run_deaktiviert_wirft_value_error():
    calls = []
    reg = CommandRegistry()
    reg.register(Command(id="cmd", title="Befehl", run=lambda: calls.append(1),
                          enabled=lambda: False))
    with pytest.raises(ValueError):
        reg.run("cmd")
    assert calls == []


def test_doppelte_id_wirft_value_error():
    reg = CommandRegistry()
    reg.register(Command(id="a", title="A", run=lambda: None))
    with pytest.raises(ValueError):
        reg.register(Command(id="a", title="A2", run=lambda: None))


def test_all_sortiert_nach_gruppe_und_titel():
    reg = _registry()
    titles = [(c.group, c.title) for c in reg.all()]
    assert titles == sorted(titles)


def test_unregister_entfernt_befehl():
    reg = _registry()
    reg.unregister("band.waehlen")
    with pytest.raises(KeyError):
        reg.get("band.waehlen")
    assert reg.search("band") == []


def test_run_erfolgreich_ruft_befehl_auf():
    reg = _registry()
    reg.run("vorlage.datentraeger")
    assert reg.get("vorlage.datentraeger") is not None


# 3 ----------------------------------------------------------------------------

def test_fold_groesse():
    assert fold("Größe") == "grosse"
