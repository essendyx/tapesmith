"""Kurzendpunkte."""

from __future__ import annotations

import json

import pytest
from PIL import Image

from daemon_fakes import FakeNow
from tapesmith import config as config_mod
from tapesmith.tape.profiles import list_tapes
from webapi_fakes import close_ctx, make_client, make_token

PRINT = "/api/v1/print"
PRINT_TEXT = "/api/v1/print/text"
PREVIEW = "/api/v1/preview.png"
JOBS = "/api/v1/jobs"
DOCS = "/api/v1/docs"

GULASCH = {"template": "gefriergut", "values": {"inhalt": "Gulasch"}}


@pytest.fixture
def api(tmp_path):
    client, ctx = make_client(tmp_path, now=FakeNow())
    yield client, ctx
    close_ctx(ctx)


def _no_debounce(ctx):
    ctx.service._debouncer._min_interval_s = 0


# ---------- POST /print ----------

def test_print_template_source_gui(api):
    client, ctx = api
    r = client.post(PRINT, json=GULASCH)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    entry = ctx.history().get(body["history_id"])
    assert entry.source == "gui"


def test_print_with_token_source_api(api):
    client, ctx = api
    token = make_token(ctx, "drucken")
    r = client.post(PRINT, json=GULASCH, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    entry = ctx.history().get(body["history_id"])
    assert entry.source == "api"


def test_print_session_with_source_header_mcp(api):
    client, ctx = api
    r = client.post(PRINT, json=GULASCH, headers={"X-P12-Source": "mcp"})
    assert r.status_code == 200, r.text
    entry = ctx.history().get(r.json()["history_id"])
    assert entry.source == "mcp"


def test_print_source_form(api):
    client, _ctx = api
    r = client.post(PRINT, json={"source": {"kind": "text", "lines": ["A"]}})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ok"


def test_print_both_or_neither_422(api):
    client, _ctx = api
    r = client.post(PRINT, json={"template": "x", "source": {"kind": "text", "lines": ["A"]}})
    assert r.status_code == 422
    r = client.post(PRINT, json={})
    assert r.status_code == 422


def test_print_unknown_template_404(api):
    client, _ctx = api
    r = client.post(PRINT, json={"template": "gibtsnicht-xyz", "values": {}})
    assert r.status_code == 404


def test_print_empty_text_422_kind_label(api):
    client, _ctx = api
    r = client.post(PRINT, json={"source": {"kind": "text", "lines": [""]}})
    assert r.status_code == 422
    assert r.json()["error"]["kind"] == "Label"


# ---------- Rückfragen ----------

def test_guard_confirmation_session_gui(api):
    client, ctx = api
    r = client.post(PRINT, json={"source": {"kind": "text", "lines": ["Sechs"]}, "options": {"copies": 6}})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "bestätigung_nötig"
    assert ctx.history().search("", 50) == []
    assert not ctx.service._test_transport.written

    r = client.post(PRINT, json={"source": {"kind": "text", "lines": ["Sechs"]},
                                 "options": {"copies": 6, "confirmed": True}})
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_guard_confirmation_token_rejected_over_limit(api):
    client, ctx = api
    _no_debounce(ctx)
    token = make_token(ctx, "drucken")
    headers = {"Authorization": f"Bearer {token}"}

    r = client.post(PRINT, json={"source": {"kind": "text", "lines": ["A"]}, "options": {"copies": 5}},
                    headers=headers)
    assert r.status_code == 200
    assert r.json()["status"] == "ok"

    written_before = len(ctx.service._test_transport.written)
    r = client.post(PRINT, json={"source": {"kind": "text", "lines": ["B"]}, "options": {"copies": 6}},
                    headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "abgelehnt"
    assert any("kann nicht bestätigen" in reason for reason in body["reasons"])
    assert len(ctx.service._test_transport.written) == written_before

    r = client.post(PRINT, json={"source": {"kind": "text", "lines": ["C"]},
                                 "options": {"copies": 6, "confirmed": True}}, headers=headers)
    assert r.status_code == 200
    assert r.json()["status"] == "abgelehnt"


def test_tape_confirmation_with_token(api):
    client, ctx = api
    token = make_token(ctx, "drucken")
    headers = {"Authorization": f"Bearer {token}"}
    paper = next(t for t in list_tapes() if t.material == "papier")
    config_mod.save_config({"tape": {"current": paper.id}})
    definition = {"schema_version": 2, "name": "nurplastik",
                 "fields": [{"id": "n", "label": "Nummer", "type": "counter"}],
                 "layout": {"lines": ["Nr {n}"]}, "tapes": ["material:kunststoff"]}
    source = {"kind": "template", "template": "nurplastik", "values": {}, "definition": definition}

    r = client.post(PRINT, json={"source": source}, headers=headers)
    assert r.status_code == 200
    assert r.json()["status"] == "bestätigung_nötig"

    r = client.post(PRINT, json={"source": source, "options": {"confirmed": True}}, headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    entry = ctx.history().get(body["history_id"])
    assert entry.source == "api"


# ---------- POST /print/text ----------

def test_print_text_field(api):
    client, _ctx = api
    r = client.post(PRINT_TEXT, json={"text": "A\nB"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ok"


def test_print_text_too_many_lines_422(api):
    client, _ctx = api
    r = client.post(PRINT_TEXT, json={"lines": ["1", "2", "3", "4"]})
    assert r.status_code == 422


def test_print_text_neither_field_422(api):
    client, _ctx = api
    r = client.post(PRINT_TEXT, json={})
    assert r.status_code == 422


def test_print_text_both_fields_422(api):
    client, _ctx = api
    r = client.post(PRINT_TEXT, json={"lines": ["A"], "text": "B"})
    assert r.status_code == 422


# ---------- GET /preview.png ----------

def test_preview_png_text(api):
    client, _ctx = api
    r = client.get(PREVIEW, params={"text": "Hallo"})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "image/png"
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_preview_png_raster_mode_1(api):
    client, _ctx = api
    r = client.get(PREVIEW, params={"text": "Hallo", "raster": 1})
    assert r.status_code == 200
    import io

    img = Image.open(io.BytesIO(r.content))
    assert img.mode == "1"


def test_preview_png_template(api):
    client, _ctx = api
    r = client.get(PREVIEW, params={"template": "gefriergut", "values": json.dumps({"inhalt": "Gulasch"})})
    assert r.status_code == 200


def test_preview_png_bad_values_422(api):
    client, _ctx = api
    r = client.get(PREVIEW, params={"template": "gefriergut", "values": "kaputt"})
    assert r.status_code == 422


def test_preview_png_neither_field_422(api):
    client, _ctx = api
    r = client.get(PREVIEW)
    assert r.status_code == 422


def test_preview_png_query_token(tmp_path):
    client, ctx = make_client(tmp_path, now=FakeNow())
    token = make_token(ctx, "drucken")
    client.headers.pop("X-P12-Token", None)
    r = client.get(PREVIEW, params={"text": "Hallo", "t": token})
    assert r.status_code == 200
    close_ctx(ctx)


# ---------- GET /jobs, DELETE /jobs/{id} ----------

def test_jobs_matches_queue(api):
    client, _ctx = api
    assert client.get(JOBS).json() == client.get("/api/v1/queue").json()


def test_delete_unknown_job(api):
    client, _ctx = api
    r = client.delete(f"{JOBS}/999")
    assert r.status_code == 200
    assert r.json() == {"ok": False}


# ---------- GET /docs ----------

def test_docs_page(api):
    client, _ctx = api
    r = client.get(DOCS)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "<script" not in r.text
    assert "/api/v1/print/text" in r.text
    assert r.headers["content-security-policy"]


# ---------- Rollen ----------

def test_family_token_forbidden(api):
    client, ctx = api
    token = make_token(ctx, "familie")
    r = client.post(PRINT, json=GULASCH, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


# ---------- Routenreihenfolge ----------

def test_print_cancel_route_not_shadowed(api):
    client, _ctx = api
    r = client.post("/api/v1/print/cancel", json={"job_key": "x"})
    assert r.status_code == 200
    assert r.json() == {"cancelled": False}
