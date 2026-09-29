"""Label-API, Rendern aller Quellen (Vorschau, Hinweise, Korrekturen, Editor-Überlagerung)."""

import base64
import io

import pytest
from PIL import Image, ImageChops

from daemon_fakes import FakeNow
from tapesmith import config as config_mod
from tapesmith.render.compose import mm_to_rows
from tapesmith.templates.store import find_template
from tapesmith.webapi.labels import resolve
from webapi_fakes import close_ctx, make_client

RENDER = "/api/v1/labels/render"

COUNTER_DEF = {"schema_version": 2, "name": "zaehltest",
               "fields": [{"id": "n", "label": "Nummer", "type": "counter"}],
               "layout": {"lines": ["Nr {n}"]}}

DOC = {"version": 1, "objects": [
    {"kind": "text", "id": "t1", "x": 0, "y": 0, "w": 100, "h": 60, "text": "Hallo"},
    {"kind": "qr", "id": "q1", "x": 110, "y": 0, "w": 64, "h": 64, "data": "HTTP://L.LAN/D7"},
]}


@pytest.fixture
def api(tmp_path):
    client, ctx = make_client(tmp_path, now=FakeNow())
    yield client, ctx
    close_ctx(ctx)


def _decode(text):
    return Image.open(io.BytesIO(base64.b64decode(text)))


def _render(client, source, options=None, status=200):
    body = {"source": source}
    if options is not None:
        body["options"] = options
    r = client.post(RENDER, json=body)
    assert r.status_code == status, r.text
    return r.json()


def test_text_ok(api):
    client, ctx = api
    data = _render(client, {"kind": "text", "lines": ["pmx10 SSD-1", "SN 274913"]})
    assert data["ok"] is True
    assert data["title"] == "pmx10 SSD-1 SN 274913"
    design = _decode(data["preview"]["design_png"])
    assert design.mode == "RGB" and design.height == ctx.profile().head_dots
    assert _decode(data["preview"]["raster_png"]).mode == "1"
    assert data["font_size"] > 0
    assert "mm" in data["preview"]["info"]
    assert data["errors"] == [] and data["editor"] is None


def test_text_strips_empty_edge_lines(api):
    client, _ctx = api
    data = _render(client, {"kind": "text", "lines": ["", "Mitte", " "]})
    assert data["ok"] and data["title"] == "Mitte"


def test_text_too_long_has_fixes_that_render(api):
    client, _ctx = api
    data = _render(client, {"kind": "text", "lines": ["Eine sehr lange Zeile mit viel Text darin"],
                            "max_length_mm": 5})
    assert data["ok"] is False or data["warnings"]
    assert data["fixes"]
    fix = data["fixes"][0]
    assert fix["id"] and fix["label"]
    assert fix["source"]["kind"] == "text"
    again = _render(client, fix["source"])
    assert again["ok"] is True


def test_text_empty(api):
    client, _ctx = api
    data = _render(client, {"kind": "text", "lines": ["", "  "]})
    assert data["ok"] is False
    assert data["errors"] == ["Kein Text"]
    assert data["preview"] is None


def test_text_with_qr_and_dark_tape(api):
    client, _ctx = api
    data = _render(client, {"kind": "text", "lines": ["Doku"], "qr": "HTTP://L.LAN/D7"})
    assert data["ok"]
    assert data["qr"]["version"] >= 1 and data["qr"]["decodes"] is True
    assert data["qr"]["checked"] is True
    assert "Version" in data["qr"]["text"]
    config_mod.save_config({"tape": {"current": "weiss-schwarz"}})
    dark = _render(client, {"kind": "text", "lines": ["Doku"], "qr": "HTTP://L.LAN/D7"})
    assert dark["ok"] and dark["errors"] == []
    # Dunkles Band: invertiert mit Ruhezone, der Code selbst bleibt gleich groß
    assert dark["qr"]["module_dots"] == data["qr"]["module_dots"]
    assert dark["qr"]["version"] == data["qr"]["version"]
    assert dark["preview"]["height"] == data["preview"]["height"]


def test_text_bad_font_is_not_printable(api):
    client, _ctx = api
    data = _render(client, {"kind": "text", "lines": ["x"], "font": "comic"})
    assert data["ok"] is False and data["errors"]


def test_text_bad_request_422(api):
    client, _ctx = api
    r = client.post(RENDER, json={"source": {"kind": "text", "lines": "kein Array"}})
    assert r.status_code == 422


def test_template_sample(api):
    client, _ctx = api
    sample = find_template("datentraeger").sample
    data = _render(client, {"kind": "template", "template": "datentraeger", "values": dict(sample)})
    assert data["ok"] is True, data["errors"]
    assert set(sample) <= set(data["values"])
    assert data["preview"] is not None


def test_template_missing_required(api):
    client, _ctx = api
    data = _render(client, {"kind": "template", "template": "datentraeger", "values": {"sn": ""}})
    assert data["ok"] is False
    assert data["errors"] and "fehlt" in data["errors"][0]
    assert data["preview"] is None


def test_template_unknown_404(api):
    client, _ctx = api
    r = client.post(RENDER, json={"source": {"kind": "template", "template": "gibtsnicht", "values": {}}})
    assert r.status_code == 404


def test_template_broken_definition_422(api):
    client, _ctx = api
    r = client.post(RENDER, json={"source": {"kind": "template", "template": "x", "values": {},
                                             "definition": {"schema_version": 2, "quatsch": 1}}})
    assert r.status_code == 422


def test_template_counter_peek_not_commit(api):
    client, _ctx = api
    src = {"kind": "template", "template": "zaehltest", "values": {}, "definition": COUNTER_DEF}
    first = _render(client, src)
    second = _render(client, src)
    assert first["ok"] and first["values"]["n"] == "1"
    assert second["values"]["n"] == "1"
    assert first["title"] == "Nr 1"


def test_document_editor_overlay(api):
    client, ctx = api
    data = _render(client, {"kind": "document", "document": DOC})
    assert data["ok"] is True, data["errors"]
    assert data["issues"] == []
    editor = data["editor"]
    assert set(editor["boxes"]) == {"t1", "q1"}
    assert editor["boxes"]["t1"] == [0, 0, 100, 60]
    assert "t1" in editor["font_sizes"]
    assert editor["codes"]["q1"]["kind"] == "qr" and editor["codes"]["q1"]["decodes"] is True
    assert editor["codes"]["q1"]["checked"] is True
    profile = ctx.profile()
    assert abs(editor["width"] - mm_to_rows(data["preview"]["content_mm"], profile)) <= 1
    assert editor["height"] == profile.content_dots
    assert data["title"] == "Hallo HTTP://L.LAN/D7"

    mirrored = _render(client, {"kind": "document", "document": {**DOC, "mirror": True}, "title": "Spiegel"})
    assert mirrored["ok"] and mirrored["title"] == "Spiegel"
    assert mirrored["editor"]["png"] == editor["png"]
    a = _decode(mirrored["preview"]["raster_png"]).convert("L")
    b = _decode(data["preview"]["raster_png"]).convert("L")
    assert ImageChops.difference(a, b).getbbox() is not None


def test_document_invalid_object(api):
    client, _ctx = api
    doc = {"version": 1, "objects": [{"kind": "text", "id": "t1", "x": 0, "y": 0, "w": 100, "h": 60,
                                      "text": "Hallo", "size": 2}]}
    data = _render(client, {"kind": "document", "document": doc})
    assert data["ok"] is False and data["errors"]
    assert data["preview"] is None


def test_document_render_error_issue(api):
    client, _ctx = api
    doc = {"version": 1, "objects": [{"kind": "qr", "id": "q1", "x": 0, "y": 0, "w": 60, "h": 60, "data": ""}]}
    data = _render(client, {"kind": "document", "document": doc})
    assert data["ok"] is False
    assert any(e.startswith("q1: ") for e in data["errors"])
    assert any(i["object_id"] == "q1" and i["level"] == "error" for i in data["issues"])
    assert data["editor"] is not None


def test_qr_wifi_title_without_password(api):
    client, _ctx = api
    data = _render(client, {"kind": "qr", "content": {"type": "wifi", "ssid": "Heim", "password": "geheim123",
                                                      "security": "WPA", "hidden": False},
                            "lines": ["Gäste"], "error": "m"})
    assert data["ok"] is True
    assert "geheim123" not in data["title"]
    assert "Heim" in data["title"]
    assert data["fixes"] == [] or all("geheim123" not in str(f) for f in data["fixes"])


def test_qr_url_auto(api):
    client, _ctx = api
    data = _render(client, {"kind": "qr", "content": {"type": "url", "url": "l.lan/d7", "uppercase": True},
                            "lines": [], "error": "auto"})
    assert data["ok"] is True
    assert data["qr"]["error"]
    assert data["qr"]["decodes"] is True
    assert data["qr"]["checked"] is True


def test_qr_invalid_content_not_printable(api):
    client, _ctx = api
    data = _render(client, {"kind": "qr", "content": {"type": "url", "url": "ftp://x"}, "lines": [],
                            "error": "m"})
    assert data["ok"] is False and data["errors"]


def test_calibration(api):
    client, _ctx = api
    ruler = _render(client, {"kind": "calibration", "which": "ruler"})
    assert ruler["ok"] and ruler["title"] == "Kalibrierung Lineal"
    assert 99 <= ruler["preview"]["content_mm"] <= 110
    edge = _render(client, {"kind": "calibration", "which": "edge"})
    assert edge["ok"] and edge["title"] == "Kalibrierung Kantentest"
    r = client.post(RENDER, json={"source": {"kind": "calibration", "which": "quatsch"}})
    assert r.status_code == 422


def test_testlabel(api):
    client, ctx = api
    data = _render(client, {"kind": "test"})
    assert data["ok"] and data["title"] == "Testlabel"
    resolved = resolve(ctx, {"kind": "test"})
    assert resolved.meta.kind == "test"


def test_unknown_kind_422(api):
    client, _ctx = api
    r = client.post(RENDER, json={"source": {"kind": "quatsch"}})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["kind"] and "quatsch" in err["message"]


def test_bad_options_422(api):
    client, _ctx = api
    r = client.post(RENDER, json={"source": {"kind": "test"}, "options": {"copies": 0}})
    assert r.status_code == 422


def test_copies_in_preview(api):
    client, _ctx = api
    data = _render(client, {"kind": "text", "lines": ["A"]}, options={"copies": 6})
    assert data["ok"] is True
    assert data["preview"]["labels"] == 6
    assert data["preview"]["decision"]["needs_confirmation"] is True


def test_fonts(api):
    client, _ctx = api
    r = client.get("/api/v1/labels/fonts")
    assert r.status_code == 200
    fonts = {f["id"]: f["name"] for f in r.json()["fonts"]}
    assert fonts["sans"] == "Sans" and fonts["mono"].startswith("Mono")
    assert fonts["sans-bold"] == "Sans fett"


def test_recent_texts_empty(api):
    client, _ctx = api
    r = client.get("/api/v1/labels/recent-texts?n=3")
    assert r.status_code == 200 and r.json() == {"items": []}


def test_template_schriftgroesse_wird_angewendet(api):
    client, _ctx = api
    values = {"belegung": "A\nKabelbinder", "schriftgroesse": "9"}
    data = _render(client, {"kind": "template", "template": "raster-patchpanel", "values": values})
    assert data["ok"] is True, data["errors"]
    assert any("verkleinert" in w for w in data["warnings"])
    bad = _render(client, {"kind": "template", "template": "raster-patchpanel",
                           "values": {"belegung": "A", "schriftgroesse": "riesig"}})
    assert bad["ok"] is False and "Schriftgröße" in bad["errors"][0]


def test_text_texthoehe_mm(api):
    client, _ctx = api
    small = _render(client, {"kind": "text", "lines": ["Hallo"], "text_height_mm": 3})
    assert small["ok"] is True and small["font_size"] == 24
    big = _render(client, {"kind": "text", "lines": ["Hallo", "Welt", "drei"], "text_height_mm": 9})
    assert big["ok"] is True and big["font_size"] < 72
    assert any("verkleinert" in w for w in big["warnings"])
    bad = client.post(RENDER, json={"source": {"kind": "text", "lines": ["x"], "text_height_mm": 40}})
    assert bad.status_code == 422
