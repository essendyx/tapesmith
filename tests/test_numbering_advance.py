"""`NumberRanges.advance_to`: hebt den Nummernkreis auf `max(lokal, n)` an,
senkt ihn nie, fehlender Kreis ergibt `KeyError`. Zusammenspiel mit `reserve` bleibt dublettenfrei,
auch über zwei Instanzen auf derselben Datei."""

from tapesmith import numbering


def test_advance_to_hebt_an(tmp_path):
    ranges = numbering.NumberRanges(tmp_path / "nummernkreise.json")
    ranges.define("asn", start=1, prefix="ASN", width=5)
    r = ranges.advance_to("asn", 42)
    assert r.next == 42
    assert ranges.get("asn").next == 42


def test_advance_to_senkt_nie(tmp_path):
    ranges = numbering.NumberRanges(tmp_path / "nummernkreise.json")
    ranges.define("asn", start=50, prefix="ASN", width=5)
    r = ranges.advance_to("asn", 42)
    assert r.next == 50
    assert ranges.get("asn").next == 50


def test_advance_to_gleicher_wert_bleibt_unveraendert(tmp_path):
    ranges = numbering.NumberRanges(tmp_path / "nummernkreise.json")
    ranges.define("asn", start=42, prefix="ASN", width=5)
    r = ranges.advance_to("asn", 42)
    assert r.next == 42


def test_advance_to_fehlender_kreis(tmp_path):
    ranges = numbering.NumberRanges(tmp_path / "nummernkreise.json")
    try:
        ranges.advance_to("asn", 42)
        assert False, "KeyError erwartet"
    except KeyError:
        pass


def test_advance_to_gibt_aktuellen_stand_zurueck(tmp_path):
    ranges = numbering.NumberRanges(tmp_path / "nummernkreise.json")
    ranges.define("asn", start=1, prefix="ASN", width=5)
    r = ranges.advance_to("asn", 10)
    assert r.key == "asn"
    assert r.prefix == "ASN"
    assert r.width == 5


def test_advance_to_und_reserve_bleiben_dublettenfrei_ueber_zwei_instanzen(tmp_path):
    path = tmp_path / "nummernkreise.json"
    a = numbering.NumberRanges(path)
    b = numbering.NumberRanges(path)
    a.define("asn", start=1, prefix="ASN", width=5)

    # Erste Instanz reserviert 1..5.
    first = a.reserve("asn", 5)
    assert first == [f"ASN{n:05d}" for n in range(1, 6)]

    # Paperless meldet inzwischen next_asn = 3 (schon lokal überholt): advance_to hebt nicht ab,
    # eine zweite Instanz reserviert dennoch dublettenfrei weiter bei 6.
    b.advance_to("asn", 3)
    second = b.reserve("asn", 2)
    assert second == ["ASN00006", "ASN00007"]

    # Paperless meldet einen höheren Stand als beide Instanzen kennen: wird übernommen.
    a.advance_to("asn", 100)
    third = a.reserve("asn", 1)
    assert third == ["ASN00100"]
