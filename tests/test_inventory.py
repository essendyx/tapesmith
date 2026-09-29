"""Tests für `inventory.py`: Boxen, Gegenstände, Suche, Verleih, Label-Inhalte, Rendern."""

from datetime import date, datetime

import pytest

from tapesmith.device.profile import load_profile
from tapesmith.inventory import (
    Box,
    InventoryStore,
    Item,
    Loan,
    contents_lines,
    loan_lines,
    render_box_label,
    render_lines_label,
)
from tapesmith.templates.fill import CounterStore

PROFILE = load_profile()


def make_store(tmp_path, clock=None):
    kwargs = {} if clock is None else {"clock": clock}
    return InventoryStore(tmp_path / "inv.sqlite3", **kwargs)


# ---------- Boxen ----------

def test_add_box_und_auflisten_natuerliche_sortierung(tmp_path):
    with make_store(tmp_path) as store:
        store.add_box("BOX-10", "Dachboden")
        store.add_box("BOX-2", "Keller")
        ids = [b.id for b in store.boxes()]
        assert ids == ["BOX-2", "BOX-10"]


def test_add_box_doppelte_id_wirft_value_error(tmp_path):
    with make_store(tmp_path) as store:
        store.add_box("BOX-07", "Keller Regal 2")
        with pytest.raises(ValueError):
            store.add_box("BOX-07", "Anderswo")


def test_add_box_ungueltige_id_wirft_value_error(tmp_path):
    with make_store(tmp_path) as store:
        with pytest.raises(ValueError):
            store.add_box("box mit leerzeichen", "Keller")


def test_update_box_aendert_ort_und_notiz(tmp_path):
    with make_store(tmp_path) as store:
        store.add_box("BOX-07", "Keller Regal 2")
        updated = store.update_box("BOX-07", location="Dachboden", note="neu")
        assert updated.location == "Dachboden"
        assert updated.note == "neu"
        assert store.box("BOX-07").location == "Dachboden"


def test_update_box_unbekannt_wirft_key_error(tmp_path):
    with make_store(tmp_path) as store:
        with pytest.raises(KeyError):
            store.update_box("BOX-99", location="x")


def test_box_unbekannt_wirft_key_error(tmp_path):
    with make_store(tmp_path) as store:
        with pytest.raises(KeyError):
            store.box("BOX-99")


def test_remove_box_mit_inhalt_wirft_value_error(tmp_path):
    with make_store(tmp_path) as store:
        store.add_box("BOX-07", "Keller Regal 2")
        store.add_item("HDMI-Adapter", box_id="BOX-07")
        with pytest.raises(ValueError):
            store.remove_box("BOX-07")


def test_remove_box_leer_geht(tmp_path):
    with make_store(tmp_path) as store:
        store.add_box("BOX-07", "Keller Regal 2")
        store.remove_box("BOX-07")
        with pytest.raises(KeyError):
            store.box("BOX-07")


# ---------- Gegenstände ----------

def test_add_item_unbekannte_box_wirft_key_error(tmp_path):
    with make_store(tmp_path) as store:
        with pytest.raises(KeyError):
            store.add_item("Akkuschrauber", box_id="BOX-99")


def test_add_item_qty_0_wirft_value_error(tmp_path):
    with make_store(tmp_path) as store:
        with pytest.raises(ValueError):
            store.add_item("Akkuschrauber", qty=0)


def test_add_item_leerer_name_wirft_value_error(tmp_path):
    with make_store(tmp_path) as store:
        with pytest.raises(ValueError):
            store.add_item("   ")


def test_move_und_remove_item(tmp_path):
    with make_store(tmp_path) as store:
        store.add_box("BOX-07", "Keller Regal 2")
        store.add_box("BOX-08", "Dachboden")
        item = store.add_item("HDMI-Adapter", box_id="BOX-07")

        moved = store.move_item(item.id, "BOX-08")
        assert moved.box_id == "BOX-08"
        assert [i.id for i in store.items("BOX-07")] == []
        assert [i.id for i in store.items("BOX-08")] == [item.id]

        freed = store.move_item(item.id, None)
        assert freed.box_id is None

        store.remove_item(item.id)
        with pytest.raises(KeyError):
            store.move_item(item.id, None)


def test_move_item_unbekannte_box_wirft_key_error(tmp_path):
    with make_store(tmp_path) as store:
        item = store.add_item("Akkuschrauber")
        with pytest.raises(KeyError):
            store.move_item(item.id, "BOX-99")


# ---------- Suche ----------

def test_search_findet_gegenstand_mit_box(tmp_path):
    with make_store(tmp_path) as store:
        store.add_box("BOX-07", "Keller Regal 2")
        store.add_item("HDMI-Adapter", box_id="BOX-07", qty=2)

        hits = store.search("hdmi")
        assert len(hits) == 1
        assert hits[0].text() == "HDMI-Adapter (2) → BOX-07, Keller Regal 2"


def test_search_zwei_woerter_eines_im_ort(tmp_path):
    with make_store(tmp_path) as store:
        store.add_box("BOX-07", "Keller Regal 2")
        store.add_item("HDMI-Adapter", box_id="BOX-07")

        hits = store.search("keller hdmi")
        assert len(hits) == 1


def test_search_ohne_box_zeigt_ohne_box(tmp_path):
    with make_store(tmp_path) as store:
        store.add_item("Ladekabel")
        hits = store.search("ladekabel")
        assert hits[0].text() == "Ladekabel (1) → ohne Box"


def test_search_leer_gibt_leere_liste(tmp_path):
    with make_store(tmp_path) as store:
        store.add_item("Ladekabel")
        assert store.search("") == []
        assert store.search("   ") == []


def test_search_kein_treffer(tmp_path):
    with make_store(tmp_path) as store:
        store.add_item("Ladekabel")
        assert store.search("nirwana") == []


# ---------- Verleih ----------

def test_lend_und_give_back(tmp_path):
    with make_store(tmp_path) as store:
        loan = store.lend("Akkuschrauber", "Max", due=date(2026, 10, 4), since=date(2026, 9, 27))
        assert loan.open
        assert [l.id for l in store.loans()] == [loan.id]

        store.give_back(loan.id, on=date(2026, 9, 28))
        assert [l.id for l in store.loans()] == []
        all_loans = store.loans(open_only=False)
        assert len(all_loans) == 1
        assert all_loans[0].returned == date(2026, 9, 28)
        assert not all_loans[0].open


def test_give_back_zweimal_wirft_value_error(tmp_path):
    with make_store(tmp_path) as store:
        loan = store.lend("Akkuschrauber", "Max", since=date(2026, 9, 27))
        store.give_back(loan.id, on=date(2026, 9, 28))
        with pytest.raises(ValueError):
            store.give_back(loan.id, on=date(2026, 9, 29))


def test_give_back_unbekannt_wirft_key_error(tmp_path):
    with make_store(tmp_path) as store:
        with pytest.raises(KeyError):
            store.give_back(999)


def test_loan_overdue(tmp_path):
    with make_store(tmp_path) as store:
        loan = store.lend("Akkuschrauber", "Max", due=date(2026, 9, 20), since=date(2026, 9, 1))
        assert loan.overdue(date(2026, 9, 27))
        assert not loan.overdue(date(2026, 9, 10))

        returned = store.give_back(loan.id, on=date(2026, 9, 21))
        assert not returned.overdue(date(2026, 9, 27))  # nicht mehr offen


def test_lend_ohne_since_nutzt_clock(tmp_path):
    with make_store(tmp_path, clock=lambda: datetime(2026, 9, 27, 12, 0)) as store:
        loan = store.lend("Akkuschrauber", "Max")
        assert loan.since == date(2026, 9, 27)


def test_loan_getter(tmp_path):
    with make_store(tmp_path) as store:
        loan = store.lend("Akkuschrauber", "Max", since=date(2026, 9, 27))
        assert store.loan(loan.id) == loan
        with pytest.raises(KeyError):
            store.loan(999)


# ---------- Persistenz ----------

def test_persistenz_ueber_neuoeffnen(tmp_path):
    path = tmp_path / "inv.sqlite3"
    store = InventoryStore(path)
    store.add_box("BOX-07", "Keller Regal 2")
    store.add_item("HDMI-Adapter", box_id="BOX-07")
    store.close()

    reopened = InventoryStore(path)
    try:
        assert [b.id for b in reopened.boxes()] == ["BOX-07"]
        assert [i.name for i in reopened.items("BOX-07")] == ["HDMI-Adapter"]
    finally:
        reopened.close()


# ---------- Label-Inhalte ----------

def test_contents_lines_zwoelf_gegenstaende_drei_zeilen_mit_rest(tmp_path):
    with make_store(tmp_path) as store:
        box = store.add_box("BOX-07", "Keller Regal 2")
        items = [store.add_item(f"Teil{n:02d}", box_id="BOX-07") for n in range(12)]

    lines = contents_lines(box, items, max_lines=3)
    assert len(lines) == 3
    assert lines[0] == "BOX-07 · Keller Regal 2"
    assert lines[-1].rstrip().endswith(")")
    assert "+" in lines[-1]
    for line in lines:
        assert len(line) <= 32


def test_contents_lines_alles_passt_kein_rest(tmp_path):
    box = Box(id="BOX-01", location="Regal", note="", created=datetime(2026, 9, 27))
    items = [Item(id=1, box_id="BOX-01", name="Kabel", qty=2, note="")]
    lines = contents_lines(box, items)
    assert lines == ("BOX-01 · Regal", "2× Kabel")


def test_loan_lines_datumsformat_mit_und_ohne_due():
    loan_mit_due = Loan(id=1, item="Akkuschrauber", person="Max", since=date(2026, 9, 27),
                        due=date(2026, 10, 4), returned=None, note="")
    assert loan_lines(loan_mit_due) == ("Verliehen an Max", "seit 27.09.2026 · bis 04.10.2026")

    loan_ohne_due = Loan(id=2, item="Akku", person="Max", since=date(2026, 9, 27),
                         due=None, returned=None, note="")
    assert loan_lines(loan_ohne_due) == ("Verliehen an Max", "seit 27.09.2026")


# ---------- Rendern ----------

def test_render_box_label(tmp_path):
    box = Box(id="BOX-07", location="Keller Regal 2", note="", created=datetime(2026, 9, 27))
    counters = CounterStore(tmp_path / "c.json")

    result, meta, counter_keys = render_box_label(box, PROFILE, counters=counters)

    assert result.head.width == PROFILE.head_dots
    assert meta.template == "aufbewahrungsbox"
    assert meta.values["nummer"] == "BOX-07"
    assert counter_keys == ()


def test_render_box_label_ohne_counters_ist_type_error():
    box = Box(id="BOX-07", location="Keller Regal 2", note="", created=datetime(2026, 9, 27))
    with pytest.raises(TypeError):
        render_box_label(box, PROFILE)


def test_render_lines_label_ist_text_art():
    result, meta = render_lines_label(("Verliehen an Max", "seit 27.09.2026"), PROFILE,
                                      title="Verleih Akkuschrauber")
    assert meta.kind == "text"
    assert meta.title == "Verleih Akkuschrauber"
    assert result.head.width == PROFILE.head_dots
