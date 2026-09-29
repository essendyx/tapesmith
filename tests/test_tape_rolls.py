"""Tests für Restmeter je Rolle (tape.rolls)."""

import pytest

from tapesmith.tape.rolls import LOW_REST_MM, ROLL_LENGTH_MM, RollStore


def test_new_roll_und_consume_addieren_und_lesen_ueber_neue_instanz(app_home):
    store = RollStore()
    store.new_roll("schwarz-weiss")
    store.consume(1000)
    store.consume(1000)

    store2 = RollStore()
    assert store2.remaining_mm() == 2000
    assert store2.current().jobs == 2
    assert store2.current().tape_id == "schwarz-weiss"


def test_consume_ohne_rolle_gibt_none_ohne_fehler(app_home):
    store = RollStore()
    assert store.consume(500) is None
    assert not store.path.exists()


def test_check_meldungen(app_home):
    store = RollStore()
    store.new_roll("schwarz-weiss")
    store.consume(2000)  # remaining = 2000

    reicht_nicht = store.check(2500)
    assert len(reicht_nicht) == 1
    assert "reicht wahrscheinlich nicht" in reicht_nicht[0]

    fast_leer = store.check(1800)
    assert len(fast_leer) == 1
    assert "fast leer" in fast_leer[0]

    leer = store.check(100)
    assert leer == []


def test_check_ohne_rolle_ist_leer(app_home):
    store = RollStore()
    assert store.check(100) == []


def test_mark_empty_lernt_faktor_und_beendet_rolle(app_home):
    store = RollStore()
    store.new_roll("schwarz-weiss")
    store.consume(100)

    factor = store.mark_empty(3800)
    assert factor == pytest.approx(0.95)
    assert store.current() is None

    store.new_roll("schwarz-weiss")
    assert store.remaining_mm() == pytest.approx(3800)


def test_mark_empty_faktor_wird_geklemmt(app_home):
    store = RollStore()
    store.new_roll("schwarz-weiss")
    assert store.mark_empty(10000) == pytest.approx(1.5)

    store.new_roll("schwarz-weiss")
    assert store.mark_empty(1) == pytest.approx(0.5)


def test_summary_mit_und_ohne_label_mm(app_home):
    store = RollStore()
    store.new_roll("schwarz-weiss")
    store.consume(ROLL_LENGTH_MM - 600)  # remaining = 600

    text = store.summary(72)
    assert "noch ca. 0,6 m" in text
    assert "±" in text
    assert "≈ 8 Etiketten à 72 mm" in text

    text_ohne = store.summary()
    assert "noch ca. 0,6 m" in text_ohne
    assert "Etiketten" not in text_ohne


def test_summary_ohne_rolle(app_home):
    store = RollStore()
    assert "Neue Rolle" in store.summary()


def test_new_roll_uebernimmt_gelernten_faktor(app_home):
    store = RollStore()
    store.new_roll("schwarz-weiss")
    store.mark_empty(2000)  # factor 0.5
    state = store.new_roll("schwarz-weiss")
    assert state.factor == pytest.approx(0.5)


# ---------- Rollen je Band (Restmeter-Zähler je Rolle) ----------

def test_rollen_je_band_getrennt(app_home):
    store = RollStore()
    store.new_roll("schwarz-weiss")
    store.new_roll("weiss-schwarz", length_mm=2000.0)
    store.consume(500, tape_id="weiss-schwarz")
    assert store.current("schwarz-weiss").used_mm == 0
    assert store.current("weiss-schwarz").used_mm == 500
    assert store.remaining_mm("weiss-schwarz") == 1500
    assert "1,5 m" in store.summary(tape_id="weiss-schwarz")
    assert "4,0 m" in store.summary(tape_id="schwarz-weiss")


def test_ohne_tape_id_gilt_das_band_aus_der_config(app_home):
    from tapesmith import config

    store = RollStore()
    store.new_roll("schwarz-weiss")                 # Rolle A (Default-Band)
    config.save_config({"tape": {"current": "weiss-schwarz"}})
    store.new_roll("weiss-schwarz", length_mm=1000.0)
    store.consume(200)                               # zählt gegen B
    assert store.current("schwarz-weiss").used_mm == 0
    assert store.current().tape_id == "weiss-schwarz"
    assert store.remaining_mm() == 800


def test_bandwechsel_ohne_rolle_zaehlt_nichts_gegen_alte_rolle(app_home):
    store = RollStore()
    store.new_roll("schwarz-weiss")
    assert store.consume(300, tape_id="schwarz-transparent") is None
    assert store.current("schwarz-weiss").used_mm == 0
    assert store.current("schwarz-transparent") is None
    assert store.check(99999, tape_id="schwarz-transparent") == []
    assert "Keine Rolle" in store.summary(tape_id="schwarz-transparent")


def test_mark_empty_nur_fuer_das_band(app_home):
    store = RollStore()
    store.new_roll("schwarz-weiss")
    store.new_roll("weiss-schwarz")
    factor = store.mark_empty(3000, tape_id="weiss-schwarz")
    assert factor == pytest.approx(0.75)
    assert store.current("weiss-schwarz") is None
    assert store.current("schwarz-weiss") is not None
    assert store.new_roll("weiss-schwarz").factor == pytest.approx(0.75)


def test_altes_dateiformat_wird_uebernommen(app_home):
    import json

    store = RollStore()
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text(json.dumps({
        "current": {"tape_id": "weiss-schwarz", "started": "2026-09-26T10:00:00", "length_mm": 4000.0,
                    "used_mm": 100.0, "jobs": 1, "factor": 1.0},
        "factor": 0.9, "history": []}), encoding="utf-8")
    assert store.current("weiss-schwarz").used_mm == 100.0
    assert store.current("schwarz-weiss") is None
    store.consume(50, tape_id="weiss-schwarz")
    assert RollStore().current("weiss-schwarz").used_mm == 150.0
    assert store.new_roll("schwarz-weiss").factor == pytest.approx(0.9)
