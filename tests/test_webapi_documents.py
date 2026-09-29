"""Dokumentablage, Import aus Verlauf und Vorlage."""

import pytest

from tapesmith.jobs import JobMeta, spec_to_dict
from tapesmith.render.compose import LabelSpec
from webapi_fakes import close_ctx, make_client

DOC = {"version": 1, "objects": [
    {"kind": "text", "id": "text1", "x": 0, "y": 0, "w": 40, "h": 20, "text": "Hallo"},
]}


@pytest.fixture
def api(tmp_path):
    client, ctx = make_client(tmp_path)
    yield client, ctx
    close_ctx(ctx)


def test_documents_crud(api):
    client, _ = api
    r = client.put("/api/v1/documents/Mein Label", json={"document": DOC})
    assert r.status_code == 200
    info = r.json()
    assert info["name"] == "Mein Label"
    assert info["objects"] == 1

    r2 = client.get("/api/v1/documents")
    assert r2.status_code == 200
    names = [d["name"] for d in r2.json()["documents"]]
    assert names == ["Mein Label"]

    r3 = client.get("/api/v1/documents/Mein Label")
    assert r3.status_code == 200
    assert r3.json()["document"]["objects"][0]["id"] == "text1"

    r4 = client.delete("/api/v1/documents/Mein Label")
    assert r4.status_code == 200

    r5 = client.get("/api/v1/documents/Mein Label")
    assert r5.status_code == 404

    r6 = client.put("/api/v1/documents/a..b", json={"document": DOC})
    assert r6.status_code == 422

    r7 = client.get("/api/v1/documents/unbekannt")
    assert r7.status_code == 404


def test_documents_draft_hidden_from_list(api):
    client, _ = api
    r = client.put("/api/v1/documents/_entwurf", json={"document": DOC})
    assert r.status_code == 200
    r2 = client.get("/api/v1/documents")
    assert r2.json()["documents"] == []


def test_from_history_text_and_sensitive(api):
    client, ctx = api
    spec = LabelSpec(lines=("Hallo Welt",), margin_mm=1.0)
    meta = JobMeta(source="gui", kind="text", title="Hallo Welt", sensitive=False,
                   spec=spec_to_dict(spec))
    entry_id = ctx.history().record(meta, landscape=None, head=None, length_mm=30.0, tape_mm=12.0)

    r = client.post(f"/api/v1/documents/from-history/{entry_id}")
    assert r.status_code == 200
    objs = r.json()["document"]["objects"]
    assert any(o["kind"] == "text" for o in objs)

    sensitive_meta = JobMeta(source="gui", kind="template", title="Geheim", sensitive=True,
                             template="datentraeger", values={})
    sensitive_id = ctx.history().record(sensitive_meta, landscape=None, head=None, length_mm=30.0,
                                        tape_mm=12.0)
    r2 = client.post(f"/api/v1/documents/from-history/{sensitive_id}")
    assert r2.status_code == 422

    r3 = client.post("/api/v1/documents/from-history/999999")
    assert r3.status_code == 404


def test_from_template(api):
    client, _ = api
    r = client.post("/api/v1/documents/from-template", json={"template": "datentraeger"})
    assert r.status_code == 200
    assert r.json()["document"]["objects"]

    r2 = client.post("/api/v1/documents/from-template", json={"template": "kabelfahne"})
    assert r2.status_code == 422
