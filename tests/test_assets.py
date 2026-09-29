"""Asset-Register mit zentralem Nummernkreis und Kurz-Link-Kopplung."""

import copy

import pytest

from homelab_fakes import mock_transport, token_file
from tapesmith.integrations import settings
from tapesmith.integrations.assets import (
    Asset,
    AssetStore,
    asset_link,
    ensure_range,
    format_id,
    label_values,
    luhn_digit,
    peek_next_ids,
    verify_id,
)
from tapesmith.integrations.errors import NotConfigured
from tapesmith.numbering import NumberRanges


def _data(**assets_values):
    data = copy.deepcopy(settings.DEFAULTS)
    data["assets"].update(assets_values)
    return data


# ---------- Prüfziffer und Formatierung ----------

def test_luhn_digit_beispiele():
    assert luhn_digit("7992739871") == "3"
    assert luhn_digit("0042") == "2"


def test_format_id_ohne_pruefziffer():
    assert format_id("HL-", 4, 42, check_digit=False) == "HL-0042"


def test_format_id_mit_pruefziffer_und_verify():
    asset_id = format_id("HL-", 4, 42, check_digit=True)
    assert asset_id == "HL-0042-2"
    assert verify_id(asset_id, "HL-", check_digit=True) is True
    assert verify_id("HL-0042-9", "HL-", check_digit=True) is False


def test_verify_id_ohne_pruefziffer():
    assert verify_id("HL-0042", "HL-", check_digit=False) is True
    assert verify_id("XX-0042", "HL-", check_digit=False) is False


# ---------- Nummernkreis ----------

def test_ensure_range_legt_kreis_an(tmp_path):
    ranges = NumberRanges(tmp_path / "nummernkreise.json")
    r = ensure_range(ranges, _data())
    assert r.key == "asset"
    assert r.prefix == "HL-"
    assert r.width == 4
    assert r.next == 1


def test_ensure_range_abweichendes_praefix_ist_fehler(tmp_path):
    ranges = NumberRanges(tmp_path / "nummernkreise.json")
    ensure_range(ranges, _data())
    with pytest.raises(ValueError, match="Präfix"):
        ensure_range(ranges, _data(prefix="AS-"))


def test_peek_next_ids_reserviert_nicht(tmp_path):
    ranges = NumberRanges(tmp_path / "nummernkreise.json")
    assert peek_next_ids(ranges, _data(), 3) == ["HL-0001", "HL-0002", "HL-0003"]
    assert not (tmp_path / "nummernkreise.json").exists()


# ---------- Reservieren ----------

def test_reserve_dreimal_eins_ergibt_fortlaufende_nummern(tmp_path):
    ranges_path = tmp_path / "nummernkreise.json"
    store = AssetStore(tmp_path / "assets.sqlite3")
    data = _data()
    ranges = NumberRanges(ranges_path)
    ids = []
    for _ in range(3):
        [asset] = store.reserve(ranges, data, 1, bezeichnung="Test")
        ids.append(asset.id)
    store.close()
    assert ids == ["HL-0001", "HL-0002", "HL-0003"]


def test_reserve_zwei_stores_gleicher_nummernkreis_keine_dublette(tmp_path):
    ranges_path = tmp_path / "nummernkreise.json"
    data = _data()
    store_a = AssetStore(tmp_path / "a.sqlite3")
    store_b = AssetStore(tmp_path / "b.sqlite3")
    ranges = NumberRanges(ranges_path)
    ids_a = [a.id for a in store_a.reserve(ranges, data, 2)]
    ids_b = [a.id for a in store_b.reserve(ranges, data, 2)]
    store_a.close()
    store_b.close()
    assert ids_a == ["HL-0001", "HL-0002"]
    assert ids_b == ["HL-0003", "HL-0004"]
    assert set(ids_a) & set(ids_b) == set()


def test_reserve_mit_pruefziffer(tmp_path):
    store = AssetStore(tmp_path / "assets.sqlite3")
    ranges = NumberRanges(tmp_path / "nummernkreise.json")
    [asset] = store.reserve(ranges, _data(check_digit=True), 1)
    store.close()
    assert asset.id == "HL-0001-8"


def test_reserve_ungueltige_anzahl_ist_fehler(tmp_path):
    store = AssetStore(tmp_path / "assets.sqlite3")
    ranges = NumberRanges(tmp_path / "nummernkreise.json")
    with pytest.raises(ValueError):
        store.reserve(ranges, _data(), 0)
    with pytest.raises(ValueError):
        store.reserve(ranges, _data(), 201)
    store.close()


# ---------- Verwerfen ----------

def test_void_setzt_status_und_nummernkreis(tmp_path):
    store = AssetStore(tmp_path / "assets.sqlite3")
    ranges = NumberRanges(tmp_path / "nummernkreise.json")
    data = _data()
    [asset] = store.reserve(ranges, data, 1)
    voided = store.void(ranges, data, asset.id, "Fehldruck")
    store.close()
    assert voided.status == "verworfen"
    assert "Fehldruck" in voided.notiz
    r = ranges.get("asset")
    assert len(r.voided) == 1
    assert r.voided[0]["number"] == "HL-0001"
    assert r.voided[0]["reason"] == "Fehldruck"


def test_void_unbekanntes_asset_ist_key_error(tmp_path):
    store = AssetStore(tmp_path / "assets.sqlite3")
    ranges = NumberRanges(tmp_path / "nummernkreise.json")
    with pytest.raises(KeyError):
        store.void(ranges, _data(), "HL-9999", "x")
    store.close()


# ---------- Vorhandene Nummer übernehmen, Suche, Export ----------

def test_add_existing_dublette_ist_fehler(tmp_path):
    store = AssetStore(tmp_path / "assets.sqlite3")
    store.add_existing("HL-0100", bezeichnung="Alt")
    with pytest.raises(ValueError, match="existiert bereits"):
        store.add_existing("hl-0100", bezeichnung="Neu")
    store.close()


def test_find_by_serial_ohne_gross_kleinschreibung(tmp_path):
    store = AssetStore(tmp_path / "assets.sqlite3")
    store.add_existing("HL-0001", seriennummer="ABC-123")
    store.add_existing("HL-0002", seriennummer="xyz")
    hits = store.find_by_serial(" abc-123 ")
    store.close()
    assert [a.id for a in hits] == ["HL-0001"]


def test_export_csv_beginnt_mit_bom_und_kopf(tmp_path):
    store = AssetStore(tmp_path / "assets.sqlite3")
    store.add_existing("HL-0001", bezeichnung="Patchkabel")
    csv_text = store.export_csv()
    store.close()
    assert csv_text.startswith("﻿id;bezeichnung;")
    assert "HL-0001;Patchkabel" in csv_text


def test_list_natural_sort(tmp_path):
    store = AssetStore(tmp_path / "assets.sqlite3")
    store.add_existing("HL-0010")
    store.add_existing("HL-0002")
    store.add_existing("HL-0100")
    result = store.list()
    store.close()
    assert [a.id for a in result] == ["HL-0002", "HL-0010", "HL-0100"]


def test_list_status_filter(tmp_path):
    store = AssetStore(tmp_path / "assets.sqlite3")
    ranges = NumberRanges(tmp_path / "nummernkreise.json")
    data = _data()
    [a1] = store.reserve(ranges, data, 1)
    [_a2] = store.reserve(ranges, data, 1)
    store.void(ranges, data, a1.id, "x")
    result = store.list(status="aktiv")
    store.close()
    assert [a.id for a in result] == ["HL-0002"]


def test_update_unbekanntes_feld_ist_key_error(tmp_path):
    store = AssetStore(tmp_path / "assets.sqlite3")
    store.add_existing("HL-0001")
    with pytest.raises(KeyError):
        store.update("HL-0001", unbekannt="x")
    store.close()


def test_label_values():
    asset = Asset(id="HL-0042", bezeichnung="Patchkabel", kategorie="", standort="", seriennummer="",
                  host="", ziel=None, paperless_doc=None, status="aktiv", notiz="", created="", updated="")
    assert label_values(asset, "HTTPS://L.EXAMPLE.COM/HL-0042") == {
        "nummer": "HL-0042", "bezeichnung": "Patchkabel", "link": "HTTPS://L.EXAMPLE.COM/HL-0042",
    }


# ---------- asset_link ----------

def _asset(**overrides):
    base = dict(id="HL-0001", bezeichnung="Patchkabel", kategorie="", standort="", seriennummer="",
               host="", ziel=None, paperless_doc=None, status="aktiv", notiz="", created="", updated="")
    base.update(overrides)
    return Asset(**base)


def test_asset_link_dienst_eingerichtet(tmp_path):
    data = _data()
    data["shortlink"]["base_url"] = "https://l.example.com"
    data["shortlink"]["token_ref"] = token_file(tmp_path, "sl")
    asset = _asset(ziel="https://x.example/a")
    link, warnings = asset_link(data, asset, transport=mock_transport(
        {"PUT /api/links/HL-0001": (201, {"id": "HL-0001", "target": "https://x.example/a", "note": "",
                                          "created": "", "updated": "", "hits": 0})}))
    assert link == "HTTPS://L.EXAMPLE.COM/HL-0001"
    assert warnings == []


def test_asset_link_nicht_eingerichtet_mit_ziel():
    asset = _asset(ziel="https://x.example/a")
    link, warnings = asset_link(_data(), asset)
    assert link == "https://x.example/a"
    assert warnings == ["Kurz-Link-Dienst nicht eingerichtet, QR enthält die lange Adresse"]


def test_asset_link_nicht_eingerichtet_ohne_ziel():
    asset = _asset(ziel=None)
    with pytest.raises(NotConfigured):
        asset_link(_data(), asset)
