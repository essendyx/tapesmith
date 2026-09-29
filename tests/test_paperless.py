"""`integrations.paperless`: ASN, Suche, Garantie. Nur MockTransport, nie echtes Netz."""

from datetime import date, datetime

import pytest

from tapesmith import numbering
from tapesmith.integrations import paperless, settings
from tapesmith.integrations.errors import AuthFailed, TokenMissing
from tapesmith.templates.fill import CounterStore, input_fields, resolve_values
from tapesmith.templates.store import find_template

from homelab_fakes import load_json, mock_transport, token_file

# Integrationen im Produkt ohne Standardadressen: Tests nutzen neutrale Testadressen.
pytestmark = pytest.mark.usefixtures("homelab_test_defaults")

WARRANTY_FIELDS = settings.DEFAULTS["paperless"]["warranty_fields"]


def _data(tmp_path, **overrides) -> dict:
    data = {k: dict(v) for k, v in settings.DEFAULTS.items()}
    data["paperless"] = {**data["paperless"], "token_ref": token_file(tmp_path, "paperless"), **overrides}
    return data


def _client(tmp_path, routes, *, calls=None) -> paperless.PaperlessClient:
    data = _data(tmp_path)
    return paperless.PaperlessClient.from_settings(data, transport=mock_transport(routes, calls=calls))


# ---------- next_asn ----------

def test_next_asn_sendet_token_header_und_liefert_zahl(tmp_path):
    calls: list = []
    client = _client(tmp_path, {"GET /api/documents/next_asn/": load_json("paperless/next_asn.json")}, calls=calls)
    assert client.next_asn() == 42
    assert calls[0].headers["authorization"] == "Token test-token-123"


def test_accept_header_fordert_api_version_9():
    # Paperless-ngx 3.x nimmt nur noch API-Version 9 und 10 an (5 bis 8: HTTP 406).
    client = paperless.PaperlessClient("http://paperless.test", "t", transport=mock_transport({}))
    assert client._client.headers["accept"] == "application/json; version=9"


# ---------- sync_range ----------

def test_sync_range_definiert_kreis_wenn_er_fehlt(tmp_path):
    ranges = numbering.NumberRanges(tmp_path / "nummernkreise.json")
    data = _data(tmp_path)
    r = paperless.sync_range(ranges, data, 42)
    assert r.next == 42
    assert r.prefix == "ASN"
    assert r.width == 5


def test_sync_range_lokal_hoeher_bleibt_unveraendert(tmp_path):
    ranges = numbering.NumberRanges(tmp_path / "nummernkreise.json")
    ranges.define("asn", start=50, prefix="ASN", width=5)
    data = _data(tmp_path)
    r = paperless.sync_range(ranges, data, 42)
    assert r.next == 50


def test_sync_range_paperless_hoeher_hebt_an(tmp_path):
    ranges = numbering.NumberRanges(tmp_path / "nummernkreise.json")
    ranges.define("asn", start=40, prefix="ASN", width=5)
    data = _data(tmp_path)
    r = paperless.sync_range(ranges, data, 42)
    assert r.next == 42


def test_sync_range_abweichendes_praefix_wirft(tmp_path):
    ranges = numbering.NumberRanges(tmp_path / "nummernkreise.json")
    ranges.define("asn", start=1, prefix="XYZ", width=5)
    data = _data(tmp_path)
    with pytest.raises(ValueError):
        paperless.sync_range(ranges, data, 42)


# ---------- reserve_asns / void_asn / asn_number ----------

def test_reserve_asns_reserviert_und_peek_danach(tmp_path):
    ranges = numbering.NumberRanges(tmp_path / "nummernkreise.json")
    data = _data(tmp_path)
    routes = {"GET /api/documents/next_asn/": load_json("paperless/next_asn.json")}
    client = paperless.PaperlessClient.from_settings(data, transport=mock_transport(routes))
    numbers = paperless.reserve_asns(client, ranges, data, 3)
    assert numbers == ["ASN00042", "ASN00043", "ASN00044"]
    assert ranges.peek("asn") == "ASN00045"

    # Zweiter Aufruf, Paperless meldet weiterhin next_asn 42 (schon überholt): reserviert dennoch
    # dublettenfrei weiter ab dem lokalen Stand.
    client2 = paperless.PaperlessClient.from_settings(data, transport=mock_transport(routes))
    more = paperless.reserve_asns(client2, ranges, data, 2)
    assert more == ["ASN00045", "ASN00046"]


def test_void_asn_gueltig_und_ungueltig(tmp_path):
    ranges = numbering.NumberRanges(tmp_path / "nummernkreise.json")
    ranges.define("asn", start=1, prefix="ASN", width=5)
    ranges.reserve("asn", 1)
    data = _data(tmp_path)
    paperless.void_asn(ranges, data, "ASN00001", "Fehldruck")
    with pytest.raises(ValueError):
        paperless.void_asn(ranges, data, "ASN99999", "nie vergeben")


def test_asn_number_und_asn_text():
    assert paperless.asn_text("ASN", 5, 42) == "ASN00042"
    assert paperless.asn_number("ASN00042", "ASN") == 42
    with pytest.raises(ValueError):
        paperless.asn_number("XYZ00042", "ASN")


# ---------- search ----------

def test_search_baut_query_und_loest_namen_auf(tmp_path):
    calls: list = []
    routes = {
        "GET /api/documents/": load_json("paperless/documents-search.json"),
        "GET /api/correspondents/": load_json("paperless/correspondents.json"),
        "GET /api/custom_fields/": load_json("paperless/custom_fields.json"),
    }
    client = _client(tmp_path, routes, calls=calls)
    hits = client.search("Rechnung", correspondent="Media", date_from=date(2026, 1, 1),
                         date_to=date(2026, 12, 31), limit=10)
    assert len(hits) == 2
    doc_call = next(c for c in calls if c.url.path == "/api/documents/")
    params = doc_call.url.params
    assert params["query"] == "Rechnung"
    assert params["correspondent__name__icontains"] == "Media"
    assert params["created__date__gte"] == "2026-01-01"
    assert params["created__date__lte"] == "2026-12-31"
    assert params["page_size"] == "10"
    assert params["ordering"] == "-created"

    corr_call = next(c for c in calls if c.url.path == "/api/correspondents/")
    assert corr_call.url.params["id__in"] == "5"

    hit17 = next(h for h in hits if h.id == 17)
    assert hit17.correspondent == "MediaMarkt"
    assert hit17.custom["Kaufdatum"] == "2026-01-31"
    assert hit17.custom["Garantie Monate"] == "1"
    assert hit17.created == "31.01.2026"

    hit18 = next(h for h in hits if h.id == 18)
    assert hit18.correspondent is None
    assert hit18.asn == 7

    # Nur ein Aufruf je Korrespondenten/Custom-Field-Auflösung.
    assert sum(1 for c in calls if c.url.path == "/api/correspondents/") == 1
    assert sum(1 for c in calls if c.url.path == "/api/custom_fields/") == 1


def test_search_ohne_text_hat_kein_query_parameter(tmp_path):
    calls: list = []
    routes = {
        "GET /api/documents/": load_json("paperless/documents-search.json"),
        "GET /api/correspondents/": load_json("paperless/correspondents.json"),
        "GET /api/custom_fields/": load_json("paperless/custom_fields.json"),
    }
    client = _client(tmp_path, routes, calls=calls)
    client.search()
    doc_call = next(c for c in calls if c.url.path == "/api/documents/")
    assert "query" not in doc_call.url.params


def test_url_verwendet_public_url_falls_gesetzt(tmp_path):
    routes = {
        "GET /api/documents/17/": load_json("paperless/document-17.json"),
        "GET /api/correspondents/": load_json("paperless/correspondents.json"),
        "GET /api/custom_fields/": load_json("paperless/custom_fields.json"),
    }
    data = _data(tmp_path, public_url="https://paperless.example.com")
    client = paperless.PaperlessClient.from_settings(data, transport=mock_transport(routes))
    hit = client.document(17)
    assert hit.url == "https://paperless.example.com/documents/17/details"


# ---------- warranty ----------

def test_warranty_custom_field_kaufdatum_und_monate(tmp_path):
    routes = {
        "GET /api/documents/17/": load_json("paperless/document-17.json"),
        "GET /api/correspondents/": load_json("paperless/correspondents.json"),
        "GET /api/custom_fields/": load_json("paperless/custom_fields.json"),
    }
    client = _client(tmp_path, routes)
    hit = client.document(17)
    w = paperless.warranty(hit, WARRANTY_FIELDS)
    assert w.kaufdatum == "31.01.2026"
    assert w.monate == 1
    assert w.ende == "28.02.2026"
    assert w.quelle == "Custom Field Kaufdatum"
    assert w.quelle_ende == "Kaufdatum plus Laufzeit"


def test_warranty_ohne_custom_fields_nutzt_erstelldatum_und_kein_ende(tmp_path):
    hit = paperless.DocumentHit(id=1, title="Ohne Felder", created="10.05.2025", correspondent=None,
                                asn=None, custom={}, url="http://x/documents/1/details")
    w = paperless.warranty(hit, WARRANTY_FIELDS)
    assert w.kaufdatum == "10.05.2025"
    assert w.quelle == "Erstelldatum des Dokuments"
    assert w.ende is None
    assert w.quelle_ende == ""


def test_warranty_garantie_bis_hat_vorrang_vor_monaten(tmp_path):
    hit = paperless.DocumentHit(
        id=1, title="x", created="31.01.2026", correspondent=None, asn=None,
        custom={"Kaufdatum": "2026-01-31", "Garantie Monate": "24", "Garantie bis": "2029-06-30"},
        url="http://x/documents/1/details")
    w = paperless.warranty(hit, WARRANTY_FIELDS)
    assert w.ende == "30.06.2029"
    assert w.quelle_ende == "Custom Field Garantie bis"


def test_warranty_parameter_months_hat_vorrang_vor_garantie_bis(tmp_path):
    hit = paperless.DocumentHit(
        id=1, title="x", created="31.01.2026", correspondent=None, asn=None,
        custom={"Kaufdatum": "2026-01-31", "Garantie bis": "2029-06-30"},
        url="http://x/documents/1/details")
    w = paperless.warranty(hit, WARRANTY_FIELDS, months=6)
    assert w.ende == "31.07.2026"
    assert w.quelle_ende == "Laufzeit angegeben"


# ---------- warranty_values ----------

def test_values_use_garantie_bis_without_months(tmp_path):
    hit = paperless.DocumentHit(
        id=1, title="x", created="31.01.2026", correspondent=None, asn=None,
        custom={"Kaufdatum": "2026-01-31", "Garantie bis": "2029-06-30"},
        url="http://x/documents/1/details")
    w = paperless.warranty(hit, WARRANTY_FIELDS)
    values, warnings = paperless.warranty_values(w, geraet="Kaffeemaschine", link="HTTPS://L.EXAMPLE.COM/DOC-1")
    assert values["ende"] == "30.06.2029"
    assert warnings == []

    resolved = resolve_values(find_template("garantie-qr"), values, datetime(2026, 1, 1),
                              CounterStore(tmp_path / "counters.json"))
    assert resolved.values["ende"] == "30.06.2029"


def test_values_garantie_bis_wins_over_mismatching_months():
    hit = paperless.DocumentHit(
        id=1, title="x", created="31.01.2026", correspondent=None, asn=None,
        custom={"Kaufdatum": "2026-01-31", "Garantie Monate": "24", "Garantie bis": "2029-06-30"},
        url="http://x/documents/1/details")
    w = paperless.warranty(hit, WARRANTY_FIELDS)
    values, warnings = paperless.warranty_values(w, geraet="Kaffeemaschine", link="L")
    assert values["ende"] == "30.06.2029"


def test_values_fallback_24_months_with_warning():
    hit = paperless.DocumentHit(id=1, title="x", created="31.01.2026", correspondent=None, asn=None,
                                custom={"Kaufdatum": "2026-01-31"}, url="http://x/documents/1/details")
    w = paperless.warranty(hit, WARRANTY_FIELDS)
    values, warnings = paperless.warranty_values(w, geraet="Kaffeemaschine", link="L")
    assert values["ende"] == "31.01.2028"
    assert warnings == ["Garantiedauer unbekannt, 24 Monate ab Kaufdatum angenommen"]


def test_values_keys_sind_teilmenge_der_eingabefelder():
    hit = paperless.DocumentHit(id=1, title="x", created="31.01.2026", correspondent=None, asn=None,
                                custom={}, url="http://x/documents/1/details")
    w = paperless.warranty(hit, WARRANTY_FIELDS)
    values, _ = paperless.warranty_values(w, geraet="Kaffeemaschine", link="L")
    assert set(values) == {"geraet", "kaufdatum", "ende", "link"}
    template = find_template("garantie-qr")
    assert set(values) <= {f.id for f in input_fields(template)}
    ende_field = template.field("ende")
    assert ende_field.type == "input"


# ---------- Fehler ----------

def test_401_ergibt_auth_failed(tmp_path):
    routes = {"GET /api/documents/next_asn/": (401, {"detail": "nope"})}
    client = _client(tmp_path, routes)
    with pytest.raises(AuthFailed):
        client.next_asn()


def test_fehlendes_token_ergibt_token_missing_mit_paperless(tmp_path):
    data = {k: dict(v) for k, v in settings.DEFAULTS.items()}
    data["paperless"] = {**data["paperless"], "token_ref": f"file:{tmp_path / 'missing'}"}
    with pytest.raises(TokenMissing) as excinfo:
        paperless.PaperlessClient.from_settings(data)
    assert excinfo.value.what == "Paperless"
