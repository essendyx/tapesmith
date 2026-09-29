"""Router /homelab/paperless/* (ASN-Serien, Garantie-Etikett)."""

from __future__ import annotations

import json

import httpx
import pytest

from homelab_fakes import load_json, mock_transport, router_client, token_file, write_homelab
from tapesmith.integrations import paperless
from tapesmith.webapi import batchapi, routes_paperless
from webapi_fakes import close_ctx

# Integrationen im Produkt ohne Standardadressen: Tests nutzen neutrale Testadressen.
pytestmark = pytest.mark.usefixtures("homelab_test_defaults")

ROUTES = {
    "GET /api/documents/next_asn/": load_json("paperless/next_asn.json"),
    "GET /api/documents/": load_json("paperless/documents-search.json"),
    "GET /api/documents/17/": load_json("paperless/document-17.json"),
    "GET /api/correspondents/": load_json("paperless/correspondents.json"),
    "GET /api/custom_fields/": load_json("paperless/custom_fields.json"),
}


@pytest.fixture
def api(tmp_path):
    write_homelab({"paperless": {"token_ref": token_file(tmp_path, "paperless")}})
    client, ctx = router_client(tmp_path, routes_paperless.router,
                                extras={"transports": {"paperless": mock_transport(ROUTES)}})
    yield client, ctx
    close_ctx(ctx)


# ---------- asn/next ----------

def test_asn_next_reserviert_nicht(api, tmp_path):
    client, _ctx = api
    response = client.get("/api/v1/homelab/paperless/asn/next")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["paperless_next"] == 42
    assert body["local_next"] is None
    assert body["next"] == "ASN00042"
    assert body["prefix"] == "ASN"
    assert body["hint"] == paperless.SCAN_TEST_HINT
    assert not _numbering_file(tmp_path).exists()


def _numbering_file(tmp_path):
    from tapesmith import paths
    return paths.app_dir() / "nummernkreise.json"


# ---------- asn/reserve ----------

def test_asn_reserve_reserviert_drei_und_legt_pending_table_an(api):
    client, ctx = api
    response = client.post("/api/v1/homelab/paperless/asn/reserve", json={"count": 3})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["numbers"] == ["ASN00042", "ASN00043", "ASN00044"]
    assert body["template"] == "asn"

    table = batchapi.load_source(ctx, {"type": "pending", "id": body["pending_id"]})
    assert table.headers == ("asn",)
    assert table.rows == (("ASN00042",), ("ASN00043",), ("ASN00044",))


# ---------- asn/void ----------

def test_asn_void(api):
    client, _ctx = api
    client.post("/api/v1/homelab/paperless/asn/reserve", json={"count": 1})
    response = client.post("/api/v1/homelab/paperless/asn/void",
                           json={"asn": "ASN00042", "reason": "Fehldruck"})
    assert response.status_code == 200
    assert response.json() == {"ok": True}


# ---------- documents ----------

def test_documents_with_invalid_date_is_422(api):
    client, _ctx = api
    response = client.get("/api/v1/homelab/paperless/documents", params={"date_from": "nicht-datum"})
    assert response.status_code == 422


def test_documents_returns_hits(api):
    client, _ctx = api
    response = client.get("/api/v1/homelab/paperless/documents", params={"query": "Rechnung"})
    assert response.status_code == 200, response.text
    docs = response.json()["documents"]
    assert len(docs) == 2
    assert docs[0]["id"] == 17
    assert docs[0]["correspondent"] == "MediaMarkt"


# ---------- warranty ----------

def test_warranty_ohne_kurzlink_dienst(api):
    client, _ctx = api
    response = client.get("/api/v1/homelab/paperless/documents/17/warranty")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["warranty"]["kaufdatum"] == "31.01.2026"
    assert body["label"]["template"] == "garantie-qr"
    assert set(body["label"]["values"]) == {"geraet", "kaufdatum", "ende", "link"}
    assert body["label"]["values"]["link"] == body["warranty"]["document"]["url"]
    assert "QR enthält die lange Paperless-Adresse" in body["warnings"]


def test_warranty_mit_kurzlink_dienst(tmp_path):
    write_homelab({
        "paperless": {"token_ref": token_file(tmp_path, "paperless")},
        "shortlink": {"base_url": "https://l.example.com", "admin_url": "https://admin.l.example.com",
                     "token_ref": token_file(tmp_path, "shortlink")},
    })
    put_calls = []

    def put_handler(request):
        put_calls.append(request)
        body = json.loads(request.content)
        return httpx.Response(200, json={
            "id": "DOC-17", "target": body["target"], "note": body.get("note", ""),
            "created": "2026-01-01T00:00:00", "updated": "2026-01-01T00:00:00", "hits": 0})

    client, ctx = router_client(tmp_path, routes_paperless.router,
                                extras={"transports": {"paperless": mock_transport(ROUTES),
                                                       "shortlink": httpx.MockTransport(put_handler)}})
    try:
        response = client.get("/api/v1/homelab/paperless/documents/17/warranty", params={"geraet": "Kaffeemaschine"})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["label"]["values"]["geraet"] == "Kaffeemaschine"
        assert body["label"]["values"]["link"] == "HTTPS://L.EXAMPLE.COM/DOC-17"
        assert "QR enthält die lange Paperless-Adresse" not in body["warnings"]
        assert len(put_calls) == 1
    finally:
        close_ctx(ctx)


def test_warranty_months_overrides(api):
    client, _ctx = api
    response = client.get("/api/v1/homelab/paperless/documents/17/warranty", params={"months": 6})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["warranty"]["quelle_ende"] == "Laufzeit angegeben"
    assert body["label"]["values"]["ende"] == "31.07.2026"
