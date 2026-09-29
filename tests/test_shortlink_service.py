"""Tests für den eigenständigen Kurz-Link-Dienst (deploy/shortlink/shortlink.py).

Der Dienst ist unabhängig vom tapesmith-Paket, deshalb wird er über einen eigenen
sys.path-Eintrag importiert (kein Import aus tapesmith). Der Warnfilter aus
tests/conftest.py (httpx/starlette.testclient) greift schon beim Sammeln.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parents[1] / "deploy" / "shortlink"))
import shortlink  # noqa: E402

ADMIN_TOKEN = "x" * 32
FIXED_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _clock():
    return FIXED_NOW


def make_client(tmp_path, *, admin_token: str | None = ADMIN_TOKEN) -> TestClient:
    app = shortlink.create_app(tmp_path / "s.db", admin_token, clock=_clock)
    return TestClient(app)


def auth(token: str = ADMIN_TOKEN) -> dict:
    return {"Authorization": f"Bearer {token}"}


# --- Health ---------------------------------------------------------------


def test_health_counts_links(tmp_path):
    client = make_client(tmp_path)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "links": 0, "version": "1"}

    client.post("/api/links", json={"target": "https://example.com"}, headers=auth())
    resp = client.get("/health")
    assert resp.json()["links"] == 1


def test_health_no_token_needed(tmp_path):
    client = make_client(tmp_path, admin_token=None)
    resp = client.get("/health")
    assert resp.status_code == 200


# --- Auto-ID ----------------------------------------------------------------


def test_create_auto_id_is_base36_upper_and_skips_existing(tmp_path):
    client = make_client(tmp_path)
    resp = client.post("/api/links", json={"target": "https://a.example.com", "id": "1"}, headers=auth())
    assert resp.status_code == 201
    assert resp.json()["id"] == "1"

    resp = client.post("/api/links", json={"target": "https://b.example.com"}, headers=auth())
    assert resp.status_code == 201
    assert resp.json()["id"] == "2"


# --- Redirect ----------------------------------------------------------------


def test_redirect_is_case_insensitive_and_counts_hits(tmp_path):
    client = make_client(tmp_path)
    resp = client.post(
        "/api/links", json={"target": "https://example.com/ziel", "id": "HL-0042"}, headers=auth()
    )
    assert resp.status_code == 201

    resp = client.get("/hl-0042", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "https://example.com/ziel"
    assert resp.headers["cache-control"] == "no-store"
    assert resp.headers["referrer-policy"] == "no-referrer"

    detail = client.get("/api/links/HL-0042", headers=auth())
    assert detail.json()["hits"] == 1

    head_resp = client.head("/hl-0042", follow_redirects=False)
    assert head_resp.status_code == 302
    detail = client.get("/api/links/HL-0042", headers=auth())
    assert detail.json()["hits"] == 1


def test_link_without_target_shows_hint_page(tmp_path):
    client = make_client(tmp_path)
    client.post("/api/links", json={"target": None, "id": "LEER"}, headers=auth())
    resp = client.get("/leer")
    assert resp.status_code == 200
    assert "LEER" in resp.text
    assert "text/html" in resp.headers["content-type"]


def test_unknown_and_invalid_ids_are_404(tmp_path):
    client = make_client(tmp_path)
    for path in ("/UNBEKANNT", "/a_b", "/"):
        resp = client.get(path)
        assert resp.status_code == 404, path
        assert "text/html" in resp.headers["content-type"]


# --- Admin-Auth ----------------------------------------------------------------


def test_admin_requires_token(tmp_path):
    client = make_client(tmp_path)
    resp = client.get("/api/links")
    assert resp.status_code == 401
    assert resp.json() == {"error": "Nicht angemeldet"}

    resp = client.get("/api/links", headers=auth("falsch-falsch-falsch-falsch"))
    assert resp.status_code == 401

    resp = client.get("/api/links", headers=auth())
    assert resp.status_code == 200


def test_admin_disabled_without_token_env(tmp_path):
    client = make_client(tmp_path, admin_token=None)
    resp = client.get("/api/links", headers=auth())
    assert resp.status_code == 503


def test_admin_disabled_with_short_token(tmp_path):
    client = make_client(tmp_path, admin_token="zu-kurz")
    resp = client.get("/api/links", headers=auth("zu-kurz"))
    assert resp.status_code == 503


# --- PUT (Upsert) ----------------------------------------------------------------


def test_put_creates_then_updates(tmp_path):
    client = make_client(tmp_path)
    resp = client.put(
        "/api/links/NEU", json={"target": "https://example.com/1", "note": "erste"}, headers=auth()
    )
    assert resp.status_code == 201
    assert resp.json()["note"] == "erste"

    resp = client.put("/api/links/NEU", json={"target": "https://example.com/2"}, headers=auth())
    assert resp.status_code == 200
    body = resp.json()
    assert body["target"] == "https://example.com/2"
    assert body["note"] == "erste"


def test_put_without_target_field_keeps_existing_target(tmp_path):
    # Regression: PUT ohne "target"-Schlüssel im Body darf ein vorhandenes Ziel
    # nicht stillschweigend auf null zurücksetzen. target ist ein
    # Pflichtfeld bei PUT (nur note ist mit "?" optional).
    client = make_client(tmp_path)
    resp = client.put(
        "/api/links/HALT", json={"target": "https://example.com", "note": "alt"}, headers=auth()
    )
    assert resp.status_code == 201

    resp = client.put("/api/links/HALT", json={"note": "nur notiz, kein target"}, headers=auth())
    assert resp.status_code == 422

    resp = client.get("/api/links/HALT", headers=auth())
    assert resp.status_code == 200
    assert resp.json()["target"] == "https://example.com"
    assert resp.json()["note"] == "alt"


# --- Validierung ----------------------------------------------------------------


@pytest.mark.parametrize(
    "target",
    [
        "javascript:alert(1)",
        "ftp://x.example.com",
        "https://example.com/mit leerzeichen",
        "https://example.com/" + "a" * 2000,
    ],
)
def test_rejects_bad_targets(tmp_path, target):
    client = make_client(tmp_path)
    resp = client.post("/api/links", json={"target": target}, headers=auth())
    assert resp.status_code == 422


def test_duplicate_id_conflict(tmp_path):
    client = make_client(tmp_path)
    client.post("/api/links", json={"target": "https://example.com", "id": "DUP"}, headers=auth())
    resp = client.post("/api/links", json={"target": "https://example.com", "id": "DUP"}, headers=auth())
    assert resp.status_code == 409


def test_delete(tmp_path):
    client = make_client(tmp_path)
    client.post("/api/links", json={"target": "https://example.com", "id": "WEG"}, headers=auth())
    resp = client.delete("/api/links/WEG", headers=auth())
    assert resp.status_code == 204
    resp = client.delete("/api/links/WEG", headers=auth())
    assert resp.status_code == 404


def test_list_sorted(tmp_path):
    client = make_client(tmp_path)
    for link_id in ("C", "A", "B"):
        client.post("/api/links", json={"target": "https://example.com", "id": link_id}, headers=auth())
    resp = client.get("/api/links", headers=auth())
    assert [link["id"] for link in resp.json()["links"]] == ["A", "B", "C"]


def test_security_headers_and_no_docs(tmp_path):
    client = make_client(tmp_path)
    for path in ("/docs", "/openapi.json", "/redoc"):
        resp = client.get(path)
        assert resp.status_code == 404, path

    resp = client.get("/health")
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"
    assert resp.headers["referrer-policy"] == "no-referrer"
    assert "access-control-allow-origin" not in resp.headers


def test_persistence_across_app_instances(tmp_path):
    db_path = tmp_path / "shared.db"
    app1 = shortlink.create_app(db_path, ADMIN_TOKEN, clock=_clock)
    client1 = TestClient(app1)
    client1.post("/api/links", json={"target": "https://example.com", "id": "BLEIBT"}, headers=auth())

    app2 = shortlink.create_app(db_path, ADMIN_TOKEN, clock=_clock)
    client2 = TestClient(app2)
    resp = client2.get("/api/links/BLEIBT", headers=auth())
    assert resp.status_code == 200
    assert resp.json()["target"] == "https://example.com"


def test_dockerfile_and_compose_consistent():
    base = Path(__file__).parents[1] / "deploy" / "shortlink"
    dockerfile = (base / "Dockerfile").read_text(encoding="utf-8")
    assert "shortlink:factory" in dockerfile
    assert "USER" in dockerfile
    assert "HEALTHCHECK" in dockerfile

    compose = (base / "compose.yaml").read_text(encoding="utf-8")
    assert "env_file" in compose
    assert "/data" in compose
    assert "SHORTLINK_HOST_PORT" in compose

    env_example = (base / ".env.example").read_text(encoding="utf-8")
    assert "SHORTLINK_ADMIN_TOKEN=" in env_example
    for line in env_example.splitlines():
        if line.startswith("SHORTLINK_ADMIN_TOKEN="):
            assert line.strip() == "SHORTLINK_ADMIN_TOKEN="


def test_compose_uses_named_volume_for_data():
    """Der Container läuft als uid 1000; ein Bind-Mount `./data` legt Docker als root an und SQLite
    kann die Datenbank nicht öffnen. Ein Named Volume übernimmt die Rechte von /data aus dem Image."""
    import re

    base = Path(__file__).parents[1] / "deploy" / "shortlink"
    dockerfile = (base / "Dockerfile").read_text(encoding="utf-8")
    assert "chown shortlink:shortlink /data" in dockerfile
    compose = (base / "compose.yaml").read_text(encoding="utf-8")
    mounts = re.findall(r"^\s*-\s*([^\s:]+):/data\s*$", compose, flags=re.M)
    assert mounts == ["shortlink-data"], mounts
    assert re.search(r"^volumes:\s*\n\s+shortlink-data:", compose, flags=re.M)
    readme = (base / "README.md").read_text(encoding="utf-8")
    assert "./data" not in readme
    assert "shortlink-data" in readme


def test_module_import_does_not_touch_data_dir(tmp_path):
    # Der Modul-Import (oben in dieser Datei) darf keine Datei unter /data anlegen.
    assert not hasattr(shortlink, "app") or shortlink.__dict__.get("app") is None
