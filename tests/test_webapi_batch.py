"""Serien-/Import-API (/batch/*)."""

import base64
import io

import openpyxl
import pytest
from PIL import Image

from tapesmith import numbering
from webapi_fakes import close_ctx, make_client


@pytest.fixture
def api(tmp_path):
    client, ctx = make_client(tmp_path)
    yield client, ctx
    close_ctx(ctx)


def _create(client, name: str, definition: dict) -> None:
    r = client.post("/api/v1/templates", json={"name": name, "definition": definition})
    assert r.status_code == 200, r.text


REQ_DEFINITION = {
    "schema_version": 2, "name": "req-test",
    "fields": [{"id": "wert", "label": "Wert", "type": "input", "required": True}],
    "layout": {"lines": ["{wert}"]},
}

COUNTER_DEFINITION = {
    "schema_version": 2, "name": "counter-test",
    "fields": [{"id": "wert", "label": "Wert", "type": "counter", "format": "{:03d}"}],
    "layout": {"lines": ["{wert}"]},
}


# ================================================================ /batch/table


def test_batch_table_text(api):
    client, _ = api
    r = client.post("/api/v1/batch/table",
                    json={"source": {"type": "text", "text": "SN;Host\nA1;pmx10\nB2;pmx10"}})
    assert r.status_code == 200
    body = r.json()
    assert body["headers"] == ["SN", "Host"]
    assert body["rows"] == [["A1", "pmx10"], ["B2", "pmx10"]]


def test_batch_table_lines(api):
    client, _ = api
    r = client.post("/api/v1/batch/table", json={"source": {"type": "lines", "text": "A1\nB2"}})
    assert r.status_code == 200
    body = r.json()
    assert body["headers"] == ["Wert"]
    assert body["rows"] == [["A1"], ["B2"]]


def test_batch_table_file_xlsx(api):
    client, _ = api
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["SN", "Host"])
    ws.append(["A1", "pmx10"])
    buf = io.BytesIO()
    wb.save(buf)
    data_b64 = base64.b64encode(buf.getvalue()).decode("ascii")

    r = client.post("/api/v1/batch/table",
                    json={"source": {"type": "file", "name": "data.xlsx", "data_b64": data_b64}})
    assert r.status_code == 200
    body = r.json()
    assert body["headers"] == ["SN", "Host"]
    assert body["rows"] == [["A1", "pmx10"]]


def test_batch_table_pending(api):
    client, ctx = api
    ctx.extras["pending"] = {"abc": {"type": "table", "headers": ["SN"], "rows": [["X1"]],
                                     "source_name": "t.csv"}}
    r = client.post("/api/v1/batch/table", json={"source": {"type": "pending", "id": "abc"}})
    assert r.status_code == 200
    body = r.json()
    assert body["headers"] == ["SN"] and body["rows"] == [["X1"]]

    r2 = client.post("/api/v1/batch/table", json={"source": {"type": "pending", "id": "unbekannt"}})
    assert r2.status_code == 404


# ================================================================ /batch/plan


def test_batch_plan_table(api):
    client, _ = api
    source = {"type": "text", "text": "SN;Host\nA1;pmx10\nB2;pmx10"}
    r = client.post("/api/v1/batch/plan", json={"template": "datentraeger", "source": source})
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 2
    assert body["mapping"]["sn"] == "SN"
    assert body["summary"]
    assert len(body["previews"]) == 2


def test_batch_plan_series(api):
    client, _ = api
    _create(client, "serie-test", {
        "schema_version": 2, "name": "serie-test",
        "fields": [{"id": "wert", "label": "Wert", "type": "input"}],
        "layout": {"lines": ["{wert}"]},
    })
    r = client.post("/api/v1/batch/plan", json={
        "template": "serie-test",
        "source": {"type": "series", "fields": {"wert": "1..5"}, "count": None},
    })
    assert r.status_code == 200
    assert r.json()["count"] == 5


def test_batch_plan_missing_required_value(api):
    client, _ = api
    _create(client, "req-test", REQ_DEFINITION)
    source = {"type": "text", "text": "Wert\nA1\n\nA3"}
    r = client.post("/api/v1/batch/plan", json={"template": "req-test", "source": source})
    assert r.status_code == 200
    body = r.json()
    assert any("Zeile 2" in e for e in body["errors"])

    r2 = client.post("/api/v1/batch/print", json={"template": "req-test", "source": source,
                                                   "options": {}})
    assert r2.status_code == 422
    assert "errors" in r2.json()["error"]["details"]


# ================================================================ /batch/print


def test_batch_print_counter_and_history(api):
    client, ctx = api
    _create(client, "counter-test", COUNTER_DEFINITION)
    counters = numbering.counter_store(ctx.config())
    before = counters.peek("counter-test.wert")

    source = {"type": "lines", "text": "a\nb\nc"}
    r = client.post("/api/v1/batch/print", json={"template": "counter-test", "source": source,
                                                  "chain": True, "options": {"chain": True}})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["history_id"] is not None

    after = counters.peek("counter-test.wert")
    assert after == before + 3


def test_batch_print_confirmation_needed_does_not_count(api):
    client, ctx = api
    _create(client, "counter-test", COUNTER_DEFINITION)
    counters = numbering.counter_store(ctx.config())
    before = counters.peek("counter-test.wert")

    source = {"type": "lines", "text": "a"}
    r = client.post("/api/v1/batch/print", json={"template": "counter-test", "source": source,
                                                  "options": {"copies": 6}})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "bestätigung_nötig"

    after = counters.peek("counter-test.wert")
    assert after == before


# ================================================================ /batch/contact-sheet


def test_batch_contact_sheet(api):
    client, _ = api
    _create(client, "req-test", REQ_DEFINITION)
    source = {"type": "lines", "text": "A1\nA2"}
    r = client.post("/api/v1/batch/contact-sheet", json={"template": "req-test", "source": source})
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    image = Image.open(io.BytesIO(r.content))
    assert image.width > 0 and image.height > 0


@pytest.mark.parametrize("route", ["plan", "print", "contact-sheet"])
def test_batch_rejects_template_path(api, route):
    from tapesmith.templates.store import user_dir
    victim = user_dir().parent / "opfer.tapesmith.json"
    victim.write_text('{"schema_version": 2, "name": "opfer", "fields": [], "layout": {"lines": ["x"]}}',
                      encoding="utf-8")
    try:
        client, _ = api
        source = {"type": "text", "text": "A\nB"}
        for name in (str(victim), victim.as_posix()):
            r = client.post(f"/api/v1/batch/{route}", json={"template": name, "source": source})
            assert r.status_code == 404, (name, r.text)
    finally:
        victim.unlink(missing_ok=True)
