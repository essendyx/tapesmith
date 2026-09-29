"""Label-API, Drucken und Exportieren über den Fake-Dienst (MemoryTransport, kein Gerät)."""

import io

import pytest
from PIL import Image, ImageChops

from daemon_fakes import FakeNow
from tapesmith import config as config_mod
from tapesmith.tape.profiles import list_tapes
from tapesmith.webapi.labels import resolve
from webapi_fakes import close_ctx, make_client

PRINT = "/api/v1/labels/print"
RENDER = "/api/v1/labels/render"
EXPORT = "/api/v1/labels/export"

TEXT = {"kind": "text", "lines": ["pmx10 SSD-1", "SN 274913"]}
COUNTER_DEF = {"schema_version": 2, "name": "zaehldruck",
               "fields": [{"id": "n", "label": "Nummer", "type": "counter"}],
               "layout": {"lines": ["Nr {n}"]}}
WIFI = {"kind": "qr", "content": {"type": "wifi", "ssid": "Heim", "password": "geheim123",
                                  "security": "WPA", "hidden": False}, "lines": ["Gäste"], "error": "m"}


@pytest.fixture
def api(tmp_path):
    client, ctx = make_client(tmp_path, now=FakeNow())
    yield client, ctx
    close_ctx(ctx)


def _print(client, source, options=None, status=200):
    r = client.post(PRINT, json={"source": source, "options": options or {}})
    assert r.status_code == status, r.text
    return r.json()


def test_print_text(api):
    client, ctx = api
    transport = ctx.service._test_transport
    out = _print(client, TEXT)
    assert out["status"] == "ok"
    assert out["history_id"] is not None
    assert out["title"] == "pmx10 SSD-1 SN 274913"
    assert transport.written


def test_preview_equals_print(api):
    client, ctx = api
    resolved = resolve(ctx, TEXT)
    out = _print(client, TEXT)
    stored = ctx.history().head_image(out["history_id"])
    assert stored.size == resolved.labels[0].head.size
    assert ImageChops.difference(stored.convert("L"), resolved.labels[0].head.convert("L")).getbbox() is None


def test_copies_need_confirmation(api):
    client, ctx = api
    transport = ctx.service._test_transport
    out = _print(client, TEXT, {"copies": 6, "job_key": "k6"})
    assert out["status"] == "bestätigung_nötig"
    assert out["reasons"]
    assert not transport.written
    out = _print(client, TEXT, {"copies": 6, "confirmed": True})
    assert out["status"] == "ok"


def test_double_press_rejected(api):
    client, _ctx = api
    assert _print(client, TEXT)["status"] == "ok"
    out = _print(client, TEXT)
    assert out["status"] == "abgelehnt"


def test_counter_commits_only_on_ok(api):
    client, _ctx = api
    src = {"kind": "template", "template": "zaehldruck", "values": {}, "definition": COUNTER_DEF}
    out = _print(client, src, {"copies": 6})
    assert out["status"] == "bestätigung_nötig"
    assert client.post(RENDER, json={"source": src}).json()["values"]["n"] == "1"
    out = _print(client, src)
    assert out["status"] == "ok"
    assert client.post(RENDER, json={"source": src}).json()["values"]["n"] == "2"


def test_tape_suitability_confirmation(api):
    client, ctx = api
    transport = ctx.service._test_transport
    paper = next(t for t in list_tapes() if t.material == "papier")
    config_mod.save_config({"tape": {"current": paper.id}})
    definition = {**COUNTER_DEF, "name": "nurplastik", "tapes": ["material:kunststoff"]}
    src = {"kind": "template", "template": "nurplastik", "values": {}, "definition": definition}
    rendered = client.post(RENDER, json={"source": src}).json()
    assert rendered["tape_reason"]
    out = _print(client, src, {"job_key": "band1"})
    assert out["status"] == "bestätigung_nötig"
    assert rendered["tape_reason"] in out["reasons"]
    assert out["job_key"] == "band1"
    assert not transport.written
    out = _print(client, src, {"confirmed": True})
    assert out["status"] == "ok"


def _no_debounce(ctx):
    # Gleiches Kopfbild direkt hintereinander lehnt der Doppeldruck-Schutz ab (Kernverhalten).
    ctx.service._debouncer._min_interval_s = 0


def test_reprint_from_history(api):
    client, ctx = api
    _no_debounce(ctx)
    first = _print(client, TEXT)
    again = _print(client, {"kind": "history", "id": first["history_id"]})
    assert again["status"] == "ok"
    assert again["history_id"] != first["history_id"]
    assert again["title"].startswith(f"Nachdruck #{first['history_id']}")


def test_reprint_unknown_404(api):
    client, _ctx = api
    r = client.post(RENDER, json={"source": {"kind": "history", "id": 999}})
    assert r.status_code == 404


def test_wifi_reprint_needs_password(api):
    client, ctx = api
    _no_debounce(ctx)
    first = _print(client, WIFI)
    assert first["status"] == "ok"
    src = {"kind": "history", "id": first["history_id"]}
    rendered = client.post(RENDER, json={"source": src}).json()
    assert rendered["ok"] is False
    assert rendered["missing_secrets"] == ["password"]
    assert rendered["preview"] is None
    assert "Sensible Felder neu eingeben" in rendered["errors"][0]
    r = client.post(PRINT, json={"source": src, "options": {}})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["kind"] == "Label"
    assert err["details"]["missing_secrets"] == ["password"]
    out = _print(client, {**src, "values": {"password": "geheim123"}})
    assert out["status"] == "ok"
    assert "geheim123" not in out["title"]


def test_busy_lease(api):
    client, ctx = api
    ctx.service.lease(object(), 60)
    r = client.post(PRINT, json={"source": TEXT, "options": {"enqueue_on_offline": False}})
    assert r.status_code == 409
    out = _print(client, TEXT, {"enqueue_on_offline": True})
    assert out["status"] == "wartet"
    assert out["queue_id"] is not None


def test_not_printable_422(api):
    client, _ctx = api
    r = client.post(PRINT, json={"source": {"kind": "text", "lines": [""]}, "options": {}})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["kind"] == "Label"
    assert err["message"] == "Kein Text"
    assert err["details"]["errors"] == ["Kein Text"]


def test_export_formats(api):
    client, _ctx = api
    r = client.post(EXPORT, json={"source": TEXT, "format": "png"})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "image/png"
    assert "label-20260927-120000.png" in r.headers["content-disposition"]
    Image.open(io.BytesIO(r.content)).load()
    r = client.post(EXPORT, json={"source": TEXT, "format": "pdf"})
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")
    r = client.post(EXPORT, json={"source": TEXT, "format": "pbm"})
    assert r.headers["content-type"] == "image/x-portable-bitmap"
    assert r.content.startswith(b"P4")
    assert "label-" in r.headers["content-disposition"]
    r = client.post(EXPORT, json={"source": TEXT, "format": "gif"})
    assert r.status_code == 422
    r = client.post(EXPORT, json={"source": {"kind": "text", "lines": []}, "format": "png"})
    assert r.status_code == 422 and r.json()["error"]["kind"] == "Label"


def test_recent_texts_after_print(api):
    client, _ctx = api
    _print(client, TEXT)
    r = client.get("/api/v1/labels/recent-texts?n=5")
    assert r.status_code == 200
    assert r.json()["items"] == [["pmx10 SSD-1", "SN 274913"]]
