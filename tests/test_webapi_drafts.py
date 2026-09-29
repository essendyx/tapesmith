"""Entwürfe-API für Editor-Tabs und Absturz-Wiederherstellung."""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from tapesmith import paths
from tapesmith.webapi import drafts
from tapesmith.webapi.drafts import DraftStore
from webapi_fakes import close_ctx, make_client, make_token

SID_A = "sitzung-aaaa"
SID_B = "sitzung-bbbb"
DOC = {"version": 1, "objects": [
    {"kind": "text", "id": "t1", "x": 0, "y": 0, "w": 20, "h": 20, "text": "A"},
    {"kind": "text", "id": "t2", "x": 30, "y": 0, "w": 20, "h": 20, "text": "B"},
]}


class Clock:
    def __init__(self, start: float = 1000.0):
        self.t = start

    def __call__(self) -> float:
        return self.t


def _body(session=SID_A, **kw) -> dict:
    body = {"session": session, "title": "Etikett 1", "doc_name": None, "document": DOC, "dirty": True,
            "order": 0}
    body.update(kw)
    return body


@pytest.fixture
def env(tmp_path):
    clock = Clock()
    client, ctx = make_client(tmp_path)
    root = paths.app_dir() / drafts.DRAFTS_DIR_NAME
    store = DraftStore(root, clock=clock, now=lambda: datetime(2026, 9, 28, 12, 0, 0))
    ctx.extras["draft_store"] = store
    yield client, ctx, clock, root
    close_ctx(ctx)


def _ids(entries):
    return [d["id"] for d in entries]


def test_konstanten():
    assert drafts.DRAFTS_DIR_NAME == "drafts"
    assert drafts.ALIVE_S == 90
    assert drafts.MAX_DRAFTS == 50
    assert drafts.MAX_BYTES == 2_000_000


def test_put_und_get(env):
    client, _ctx, _clock, root = env
    r = client.put("/api/v1/drafts/entwurf-0001", json=_body())
    assert r.status_code == 200, r.text
    info = r.json()
    assert info == {"id": "entwurf-0001", "title": "Etikett 1", "doc_name": None, "dirty": True,
                    "updated": "2026-09-28T12:00:00", "objects": 2, "order": 0, "session": SID_A}
    assert (root / "entwurf-0001.json").is_file()
    full = client.get("/api/v1/drafts/entwurf-0001").json()
    assert full["document"]["objects"][1]["text"] == "B"
    assert {k: full[k] for k in info} == info


def test_get_unbekannt_404(env):
    client, *_ = env
    r = client.get("/api/v1/drafts/gibtesnicht1")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


def test_liste_eigen_verwaist_und_heartbeat(env):
    client, _ctx, clock, _root = env
    client.put("/api/v1/drafts/entwurf-0001", json=_body())
    body = client.get("/api/v1/drafts", params={"session": SID_A}).json()
    assert _ids(body["drafts"]) == ["entwurf-0001"]
    assert _ids(body["own"]) == ["entwurf-0001"]
    assert body["orphaned"] == []

    body = client.get("/api/v1/drafts", params={"session": SID_B}).json()
    assert body["own"] == [] and body["orphaned"] == []          # A lebt noch

    clock.t += 91
    body = client.get("/api/v1/drafts", params={"session": SID_B}).json()
    assert _ids(body["orphaned"]) == ["entwurf-0001"]

    r = client.post("/api/v1/drafts/heartbeat", json={"session": SID_A})
    assert r.json() == {"alive_s": 90}
    body = client.get("/api/v1/drafts", params={"session": SID_B}).json()
    assert body["orphaned"] == []


def test_nach_dienst_neustart_verwaist(env):
    client, ctx, clock, root = env
    client.put("/api/v1/drafts/entwurf-0001", json=_body())
    ctx.extras["draft_store"] = DraftStore(root, clock=clock)
    body = client.get("/api/v1/drafts", params={"session": SID_B}).json()
    assert _ids(body["orphaned"]) == ["entwurf-0001"]


def test_adopt(env):
    client, _ctx, clock, _root = env
    client.put("/api/v1/drafts/entwurf-0001", json=_body())
    clock.t += 91
    r = client.post("/api/v1/drafts/entwurf-0001/adopt", json={"session": SID_B})
    assert r.status_code == 200
    assert r.json()["session"] == SID_B
    body = client.get("/api/v1/drafts", params={"session": SID_B}).json()
    assert _ids(body["own"]) == ["entwurf-0001"]
    assert body["orphaned"] == []


def test_sortierung_nach_order_dann_updated(env):
    client, *_ = env
    client.put("/api/v1/drafts/entwurf-0003", json=_body(order=2))
    client.put("/api/v1/drafts/entwurf-0001", json=_body(order=1))
    client.put("/api/v1/drafts/entwurf-0002", json=_body(order=1))
    body = client.get("/api/v1/drafts", params={"session": SID_A}).json()
    assert _ids(body["own"])[-1] == "entwurf-0003"
    assert set(_ids(body["own"])[:2]) == {"entwurf-0001", "entwurf-0002"}


def test_delete_idempotent(env):
    client, _ctx, _clock, root = env
    client.put("/api/v1/drafts/entwurf-0001", json=_body())
    assert client.delete("/api/v1/drafts/entwurf-0001").json() == {}
    assert not (root / "entwurf-0001.json").exists()
    r = client.delete("/api/v1/drafts/entwurf-0001")
    assert r.status_code == 200 and r.json() == {}


@pytest.mark.parametrize("draft_id", ["kurz", "mit.punkt-123", "x" * 65, "..%2F..%2Fboese1"])
def test_ungueltige_id_422(env, draft_id):
    client, *_ = env
    r = client.put(f"/api/v1/drafts/{draft_id}", json=_body())
    assert r.status_code in (404, 422)
    if r.status_code == 422:
        assert r.json()["error"]["code"] == "value.invalid"


def test_ungueltige_id_und_sitzung_im_store(tmp_path):
    store = DraftStore(tmp_path / "d")
    with pytest.raises(ValueError):
        store.put("kurz", _body())
    with pytest.raises(ValueError):
        store.put("entwurf-0001", _body(session="x"))
    with pytest.raises(ValueError):
        store.list("a b")
    with pytest.raises(ValueError):
        store.put("entwurf-0001", _body(title="x" * 121))


def test_ungueltige_sitzung_und_titel_422(env):
    client, *_ = env
    r = client.put("/api/v1/drafts/entwurf-0001", json=_body(session="zu kurz"))
    assert r.status_code == 422 and r.json()["error"]["code"] == "value.invalid"
    r = client.put("/api/v1/drafts/entwurf-0001", json=_body(title="x" * 121))
    assert r.status_code == 422 and r.json()["error"]["code"] == "value.invalid"
    r = client.get("/api/v1/drafts", params={"session": "!"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "value.invalid"


def test_ungueltiges_dokument_422(env):
    client, *_ = env
    r = client.put("/api/v1/drafts/entwurf-0001", json=_body(document={"version": 1, "quatsch": True}))
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "document.invalid"


def test_zu_gross_413(env):
    client, *_ = env
    big = {"version": 1, "objects": [
        {"kind": "text", "id": "t1", "x": 0, "y": 0, "w": 20, "h": 20, "text": "A" * 2_100_000}]}
    r = client.put("/api/v1/drafts/entwurf-0001", json=_body(document=big))
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "too_large"


def test_hoechstens_50_entwuerfe(env):
    client, *_ = env
    for i in range(50):
        assert client.put(f"/api/v1/drafts/entwurf-{i:04d}", json=_body()).status_code == 200
    r = client.put("/api/v1/drafts/entwurf-0050", json=_body())
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "value.invalid"
    assert "Zu viele Entwürfe (höchstens 50)" in err["message"]
    assert client.put("/api/v1/drafts/entwurf-0001", json=_body(title="neu")).status_code == 200


def test_altlast_entwurf_wird_genau_einmal_migriert(env):
    client, *_ = env
    legacy = paths.app_dir() / "documents" / "_entwurf.p12doc.json"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(json.dumps(DOC), encoding="utf-8")
    body = client.get("/api/v1/drafts", params={"session": SID_A}).json()
    assert _ids(body["orphaned"]) == ["legacy-entwurf"]
    entry = body["orphaned"][0]
    assert entry["session"] == "legacy" and entry["title"] == "Entwurf" and entry["dirty"] is True
    assert entry["objects"] == 2
    assert not legacy.exists()
    body = client.get("/api/v1/drafts", params={"session": SID_A}).json()
    assert _ids(body["drafts"]) == ["legacy-entwurf"]


def test_migrate_legacy_direkt(tmp_path):
    root = tmp_path / "app" / "drafts"
    legacy = tmp_path / "app" / "documents" / "_entwurf.p12doc.json"
    store = DraftStore(root)
    assert store.migrate_legacy() is False
    legacy.parent.mkdir(parents=True)
    legacy.write_text(json.dumps(DOC), encoding="utf-8")
    assert store.migrate_legacy() is True
    assert store.migrate_legacy() is False
    assert store.get("legacy-entwurf")["document"]["objects"][0]["id"] == "t1"


def test_last_heartbeat_steigt(tmp_path):
    clock = Clock(5000.0)
    store = DraftStore(tmp_path / "d", clock=clock)
    store.heartbeat(SID_A)
    assert drafts.last_heartbeat() == 5000.0
    assert store.alive(SID_A)
    clock.t += 10
    store.put("entwurf-0001", _body())
    assert drafts.last_heartbeat() == 5010.0
    clock.t += 100
    assert not store.alive(SID_A)
    assert not store.alive(SID_B)


def test_rolle_drucken_403(tmp_path):
    client, ctx = make_client(tmp_path, auth=None)
    try:
        secret = make_token(ctx, "drucken")
        r = client.get("/api/v1/drafts", params={"session": SID_A},
                       headers={"Authorization": f"Bearer {secret}"})
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "auth.forbidden"
    finally:
        close_ctx(ctx)


def test_standard_store_im_app_verzeichnis(tmp_path):
    client, ctx = make_client(tmp_path)
    try:
        assert client.put("/api/v1/drafts/entwurf-0001", json=_body()).status_code == 200
        assert (paths.app_dir() / "drafts" / "entwurf-0001.json").is_file()
        assert isinstance(ctx.extras["draft_store"], DraftStore)
    finally:
        close_ctx(ctx)
