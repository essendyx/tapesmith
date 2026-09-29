"""`integrations.kleinanzeigen`: IDs, Übergänge, Etiketten."""

import copy
import dataclasses
from datetime import date

import pytest

from homelab_fakes import mock_transport, token_file
from tapesmith.integrations import settings
from tapesmith.integrations.kleinanzeigen import (
    Artikel,
    KaStore,
    article_label,
    article_link,
    ensure_range,
    normalize_id,
    reserved_label,
)
from tapesmith.numbering import NumberRanges


def _data(**shortlink_over) -> dict:
    data = copy.deepcopy(settings.DEFAULTS)
    data["shortlink"].update(shortlink_over)
    return data


def _artikel(**over) -> Artikel:
    base = dict(id="KA-001", titel="Monitorarm", preis="", anzeige=None, status="verfügbar",
               name="", datum="", ort="", notiz="", created="", updated="")
    base.update(over)
    return Artikel(**base)


# ---------- normalize_id / ensure_range ----------

def test_normalize_id():
    data = _data()
    assert normalize_id("ka-17", data) == "KA-017"
    assert normalize_id("17", data) == "KA-017"
    assert normalize_id("ka17", data) == "KA-017"
    with pytest.raises(ValueError):
        normalize_id("X-1", data)


def test_ensure_range_defines_then_detects_mismatch(tmp_path):
    ranges = NumberRanges(tmp_path / "nummernkreise.json")
    data = _data()
    r = ensure_range(ranges, data)
    assert r.prefix == "KA-" and r.width == 3
    # zweiter Aufruf mit gleichen Werten: unverändert, kein Fehler
    assert ensure_range(ranges, data).next == r.next

    mismatched = _data()
    mismatched["kleinanzeigen"] = {**mismatched["kleinanzeigen"], "prefix": "XX-"}
    with pytest.raises(ValueError, match="Präfix/Breite"):
        ensure_range(ranges, mismatched)


# ---------- add / Übergänge ----------

def test_add_vergibt_sequentielle_ids(tmp_path):
    ranges = NumberRanges(tmp_path / "nummernkreise.json")
    data = _data()
    with KaStore(tmp_path / "ka.sqlite3") as store:
        a1 = store.add(ranges, data, titel="Monitorarm")
        a2 = store.add(ranges, data, titel="Stuhl", preis="VB 40")
    assert a1.id == "KA-001"
    assert a2.id == "KA-002"
    assert a1.status == "verfügbar"
    assert a2.preis == "VB 40"


def test_reserve_dann_sell_ok_sell_dann_reserve_fehler(tmp_path):
    ranges = NumberRanges(tmp_path / "nummernkreise.json")
    data = _data()
    with KaStore(tmp_path / "ka.sqlite3") as store:
        art = store.add(ranges, data, titel="Monitorarm")
        reserved = store.reserve(art.id, "Hubert", date(2026, 9, 30))
        assert reserved.status == "reserviert"
        assert reserved.name == "Hubert"
        assert reserved.datum == "30.09.2026"

        sold = store.sell(reserved.id, "Hubert", date(2026, 10, 1))
        assert sold.status == "verkauft"
        assert sold.datum == "01.10.2026"

        with pytest.raises(ValueError, match="verkauft"):
            store.reserve(sold.id, "Anna", date(2026, 10, 5))


def test_reservieren_ersetzt_alte_reservierung(tmp_path):
    ranges = NumberRanges(tmp_path / "nummernkreise.json")
    data = _data()
    with KaStore(tmp_path / "ka.sqlite3") as store:
        art = store.add(ranges, data, titel="Kiste")
        store.reserve(art.id, "Hubert", date(2026, 9, 30))
        second = store.reserve(art.id, "Anna", date(2026, 10, 15))
    assert second.name == "Anna"
    assert second.datum == "15.10.2026"


def test_release_nur_aus_reserviert(tmp_path):
    ranges = NumberRanges(tmp_path / "nummernkreise.json")
    data = _data()
    with KaStore(tmp_path / "ka.sqlite3") as store:
        art = store.add(ranges, data, titel="Kiste")
        with pytest.raises(ValueError, match="nicht reserviert"):
            store.release(art.id)
        store.reserve(art.id, "Hubert", date(2026, 9, 30))
        released = store.release(art.id)
    assert released.status == "verfügbar"
    assert released.name == ""
    assert released.datum == ""


def test_get_normalisiert_und_unbekannte_id_ist_none(tmp_path):
    ranges = NumberRanges(tmp_path / "nummernkreise.json")
    data = _data()
    with KaStore(tmp_path / "ka.sqlite3") as store:
        store.add(ranges, data, titel="Monitorarm")
        assert store.get("ka-1").id == "KA-001"
        assert store.get("KA-999") is None


def test_list_filtert_status_und_suche(tmp_path):
    ranges = NumberRanges(tmp_path / "nummernkreise.json")
    data = _data()
    with KaStore(tmp_path / "ka.sqlite3") as store:
        store.add(ranges, data, titel="Monitorarm")
        art2 = store.add(ranges, data, titel="Stuhl")
        store.reserve(art2.id, "Hubert", date(2026, 9, 30))

        reserved_only = store.list(status="reserviert")
        assert [a.id for a in reserved_only] == [art2.id]

        found = store.list(query="stuhl")
        assert [a.id for a in found] == [art2.id]


# ---------- Etiketten ----------

def test_reserved_label_nur_bei_status_reserviert():
    art = _artikel(status="reserviert", name="Hubert", datum="30.09.2026")
    assert reserved_label(art) == {"template": "reserviert", "values": {"name": "Hubert", "bis": "30.09.2026"}}

    verf = _artikel(status="verfügbar")
    with pytest.raises(ValueError, match="nicht reserviert"):
        reserved_label(verf)


def test_article_link_mit_dienst(tmp_path):
    calls = []
    data = _data(base_url="https://l.example.com", admin_url="https://l.example.com",
                token_ref=token_file(tmp_path, "shortlink"))
    art = _artikel(anzeige="https://example.org/a/1")
    transport = mock_transport({"PUT /api/links/KA-001": (200, {
        "id": "KA-001", "target": "https://example.org/a/1", "note": "Monitorarm",
        "created": "2026-09-28T10:00:00", "updated": "2026-09-28T10:00:00", "hits": 0})}, calls=calls)

    link, warnings = article_link(data, art, transport=transport)

    assert link == "HTTPS://L.EXAMPLE.COM/KA-001"
    assert warnings == []
    assert calls[0].method == "PUT"


def test_article_link_ohne_dienst_mit_anzeige_warnt():
    data = _data()
    art = _artikel(anzeige="https://example.org/a/1")

    link, warnings = article_link(data, art)

    assert link == "https://example.org/a/1"
    assert len(warnings) == 1
    assert "Kurz-Link-Dienst" in warnings[0]


def test_article_link_ohne_beides_ist_fehler():
    data = _data()
    art = _artikel(anzeige=None)
    with pytest.raises(ValueError, match="fehlt die Anzeigen-Adresse"):
        article_link(data, art)


def test_article_label_baut_werte_und_gibt_warnungen_durch():
    data = _data()
    art = _artikel(anzeige="https://example.org/a/1", preis="25 €")

    label, warnings = article_label(data, art)

    assert label == {"template": "ka-artikel",
                     "values": {"id": "KA-001", "titel": "Monitorarm", "preis": "25 €",
                               "link": "https://example.org/a/1"}}
    assert warnings
