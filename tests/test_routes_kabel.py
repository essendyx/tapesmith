"""Router /homelab/kabel (NetBox-Import, ID-Schema, Register)."""

import base64
import json
from pathlib import Path

import pytest

from homelab_fakes import router_client, write_homelab
from tapesmith.integrations import settings
from tapesmith.numbering import NumberRanges
from tapesmith.webapi import routes_kabel
from webapi_fakes import close_ctx

DATA = Path(__file__).parent / "data" / "netbox"


def _csv_b64(name: str) -> str:
    return base64.b64encode(DATA.joinpath(name).read_bytes()).decode("ascii")


@pytest.fixture
def api(tmp_path):
    write_homelab({})
    client, ctx = router_client(tmp_path, routes_kabel.router)
    yield client, ctx
    close_ctx(ctx)


def _numbering_path() -> Path:
    from tapesmith import config

    cfg = config.load_config()
    from tapesmith.numbering import numbering_dir, FILE_NAME

    return numbering_dir(cfg) / FILE_NAME


def test_netbox_preview_assigns_no_ids(api):
    client, _ctx = api
    response = client.post("/api/v1/homelab/kabel/netbox",
                           json={"csv_b64": _csv_b64("cables-export.csv"), "assign_ids": True})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["preview_only"] is True
    new_labels = [row["kabel_id"] for row in body["rows"] if row["neu"]]
    assert new_labels == ["neu 1", "neu 2"]
    assert not _numbering_path().exists()


def test_netbox_preview_without_assign_ids_warns(api):
    client, _ctx = api
    response = client.post("/api/v1/homelab/kabel/netbox", json={"csv_b64": _csv_b64("cables-export.csv")})
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["warnings"]) == 2


def test_table_assigns_registers_and_builds_pending(api):
    client, _ctx = api
    response = client.post("/api/v1/homelab/kabel/table", json={
        "csv_b64": _csv_b64("cables-export.csv"), "assign_ids": True, "register": True,
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["count"] == 5
    assert len(body["new_ids"]) == 2
    assert body["duplicates"] == []

    reg = client.get("/api/v1/homelab/kabel/register")
    assert reg.status_code == 200
    assert len(reg.json()["entries"]) == 5


def test_table_second_import_with_register_accepts_existing_ids(api):
    client, _ctx = api
    body = {"csv_b64": _csv_b64("cables-export.csv"), "assign_ids": True, "register": True}
    first = client.post("/api/v1/homelab/kabel/table", json=body)
    assert first.status_code == 200, first.text
    # Gleiche Datei erneut importieren: die vorher vergebenen IDs sind jetzt frisch, nicht mehr leer,
    # daher werden dieselben Werte importiert (kein neues assign_ids nötig) und akzeptiert.
    second = client.post("/api/v1/homelab/kabel/table", json={
        "csv_b64": _csv_b64("cables-export.csv"), "assign_ids": False, "register": True,
    })
    assert second.status_code == 200, second.text


def test_table_batch_duplicate_is_422(api):
    client, _ctx = api
    mapping = {"kabel_id": "Side A"}  # jede Zeile bekommt eine der Spalten "SW1"/"SW2"/"PDU1" als ID -> teils gleich
    response = client.post("/api/v1/homelab/kabel/table", json={
        "csv_b64": _csv_b64("cables-export.csv"), "mapping": mapping, "register": True,
    })
    assert response.status_code == 422


def test_ids_schema_returns_24(api):
    client, _ctx = api
    response = client.post("/api/v1/homelab/kabel/ids", json={
        "mode": "schema", "ranges": [{"rack": "R1", "units": "1", "ports": "1-24"}],
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["ids"]) == 24
    assert body["ids"][0] == "R1.U01:P01"
    assert body["pending_id"] is None


def test_ids_register_existing_is_422(api):
    client, _ctx = api
    payload = {"mode": "schema", "ranges": [{"rack": "R1", "units": "1", "ports": "1"}], "register": True}
    first = client.post("/api/v1/homelab/kabel/ids", json=payload)
    assert first.status_code == 200, first.text
    second = client.post("/api/v1/homelab/kabel/ids", json=payload)
    assert second.status_code == 422


def test_ids_free_reserves_and_table(api):
    client, _ctx = api
    response = client.post("/api/v1/homelab/kabel/ids", json={"mode": "frei", "count": 3, "table": True})
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["ids"]) == 3
    assert body["pending_id"] is not None


def test_netbox_csv_too_large_is_422(api):
    client, _ctx = api
    huge = base64.b64encode(b"a" * (2 * 1024 * 1024 + 1)).decode("ascii")
    response = client.post("/api/v1/homelab/kabel/netbox", json={"csv_b64": huge})
    assert response.status_code == 422


def test_register_search_and_delete(api):
    client, _ctx = api
    client.post("/api/v1/homelab/kabel/ids", json={
        "mode": "schema", "ranges": [{"rack": "R1", "units": "1", "ports": "1"}], "register": True,
    })
    found = client.get("/api/v1/homelab/kabel/register", params={"query": "R1"})
    assert len(found.json()["entries"]) == 1
    kabel_id = found.json()["entries"][0]["id"]
    deleted = client.delete(f"/api/v1/homelab/kabel/register/{kabel_id}")
    assert deleted.json()["removed"] is True
    missing = client.delete(f"/api/v1/homelab/kabel/register/{kabel_id}")
    assert missing.json()["removed"] is False
