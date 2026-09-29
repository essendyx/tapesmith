"""Vorlagen-, Galerie- und Serien-API (feste Routen vor {name})."""

import base64
import io
import json

import pytest
from PIL import Image

from tapesmith import paths
from tapesmith.jobs import JobMeta
from tapesmith.templates.store import user_dir
from webapi_fakes import close_ctx, make_client


@pytest.fixture
def api(tmp_path):
    client, ctx = make_client(tmp_path)
    yield client, ctx
    close_ctx(ctx)


# ================================================================ Vorlagen: Liste/Details


def test_list_templates(api):
    client, _ = api
    r = client.get("/api/v1/templates")
    assert r.status_code == 200
    by_name = {t["name"]: t for t in r.json()["templates"]}
    assert "datentraeger" in by_name
    entry = by_name["datentraeger"]
    assert entry["builtin"] is True
    assert entry["kind"] == "layout"
    assert entry["input_fields"]
    assert any(f["id"] == "sn" for f in entry["input_fields"])


def test_get_template(api):
    client, _ = api
    r = client.get("/api/v1/templates/datentraeger")
    assert r.status_code == 200
    body = r.json()
    assert body["definition"]["name"] == "datentraeger"
    assert body["builtin"] is True
    assert isinstance(body["fields"], list) and body["fields"]

    r404 = client.get("/api/v1/templates/gibtsnicht")
    assert r404.status_code == 404
    assert r404.json()["error"]["kind"] == "NotFound"


# ================================================================ Vorlagen: Anlegen/Löschen


_SIMPLE_DOC = {"version": 1, "objects": [
    {"kind": "text", "id": "t1", "x": 0, "y": 0, "w": 80, "h": 20, "text": "Hallo Welt"},
]}


def test_create_and_list_own_template(api):
    client, ctx = api
    r = client.post("/api/v1/templates", json={"name": "test-vorlage", "document": _SIMPLE_DOC})
    assert r.status_code == 200
    body = r.json()
    assert body["builtin"] is False
    assert body["kind"] == "document"
    assert (user_dir() / "test-vorlage.tapesmith.json").is_file()

    r2 = client.get("/api/v1/templates")
    names = {t["name"]: t for t in r2.json()["templates"]}
    assert names["test-vorlage"]["builtin"] is False

    r3 = client.post("/api/v1/templates", json={"name": "test-vorlage", "document": _SIMPLE_DOC})
    assert r3.status_code == 422

    r4 = client.post("/api/v1/templates", json={"name": "test-vorlage", "document": _SIMPLE_DOC,
                                                 "overwrite": True})
    assert r4.status_code == 200

    r5 = client.post("/api/v1/templates", json={"name": "../x", "document": _SIMPLE_DOC})
    assert r5.status_code == 422


def test_create_template_with_placeholder_document(api):
    client, _ = api
    doc = {"version": 1, "objects": [
        {"kind": "text", "id": "t1", "x": 0, "y": 0, "w": 80, "h": 20, "text": "Wert {wert}"},
    ]}
    r = client.post("/api/v1/templates", json={"name": "platzhalter", "document": doc})
    assert r.status_code == 200
    body = r.json()
    assert any(f["id"] == "wert" and f["type"] == "input" for f in body["fields"])


def test_create_template_needs_document_or_definition(api):
    client, _ = api
    r = client.post("/api/v1/templates", json={"name": "leer"})
    assert r.status_code == 422


def test_delete_template(api):
    client, _ = api
    client.post("/api/v1/templates", json={"name": "test-vorlage", "document": _SIMPLE_DOC})
    r = client.delete("/api/v1/templates/test-vorlage")
    assert r.status_code == 200
    assert not (user_dir() / "test-vorlage.tapesmith.json").is_file()

    r2 = client.delete("/api/v1/templates/datentraeger")
    assert r2.status_code == 422

    r3 = client.delete("/api/v1/templates/gibtsnicht")
    assert r3.status_code == 404


def test_delete_template_rejects_path_traversal(api):
    client, _ = api
    victim = user_dir().parent / "opfer.tapesmith.json"
    victim.write_text("schutzbedürftig")
    try:
        # Backslashes im {name}-Segment sind für Starlette kein Verzeichnistrenner
        # (nur "/" ist verboten), Path./ behandelt sie unter Windows aber als solche.
        r = client.delete("/api/v1/templates/..\\opfer")
        assert r.status_code == 422
        assert victim.is_file()
    finally:
        victim.unlink(missing_ok=True)


_VICTIM_DEF = {
    "schema_version": 2, "name": "opfer", "description": "GEHEIM-INHALT",
    "fields": [{"id": "wert", "label": "Wert", "type": "input"}],
    "layout": {"lines": ["{wert}"]},
}


@pytest.fixture
def victim():
    """Gültige Vorlagendatei außerhalb von user_dir()/builtin_dir()."""
    path = user_dir().parent / "opfer.tapesmith.json"
    path.write_text(json.dumps(_VICTIM_DEF), encoding="utf-8")
    yield path
    path.unlink(missing_ok=True)


def _traversal_names(path):
    return [str(path), path.as_posix(), str(path).removesuffix(".tapesmith.json"), "..\\opfer", "../opfer"]


def test_get_template_rejects_path(api, victim):
    client, _ = api
    for name in _traversal_names(victim):
        r = client.get("/api/v1/templates/" + name.replace("/", "%2F"))
        assert r.status_code in (404, 422), name
        assert "GEHEIM-INHALT" not in r.text


def test_export_rejects_path(api, victim):
    client, _ = api
    for name in _traversal_names(victim):
        r = client.post("/api/v1/templates/export", json={"names": [name]})
        assert r.status_code == 404, name
        assert b"GEHEIM-INHALT" not in r.content


def test_assignment_rejects_path(api, victim):
    client, _ = api
    r = client.post("/api/v1/templates/" + str(victim).replace("/", "%2F") + "/assignment", json={})
    assert r.status_code in (404, 422)


def test_gallery_thumb_rejects_path(api, victim):
    client, _ = api
    name = str(victim).removesuffix(".tapesmith.json")
    r = client.get("/api/v1/gallery/thumb/" + name.replace("/", "%2F") + ".png")
    assert r.status_code in (404, 422)


# ================================================================ Galerie


def test_gallery_search_and_category(api):
    client, _ = api
    r = client.get("/api/v1/gallery", params={"query": "sn"})
    assert r.status_code == 200
    body = r.json()
    all_names = {t["name"] for cat in body["categories"] for t in cat["templates"]}
    assert "datentraeger" in all_names

    r2 = client.get("/api/v1/gallery", params={"category": "Datenträger"})
    body2 = r2.json()
    cat_names = {cat["name"] for cat in body2["categories"]}
    assert cat_names == {"Datenträger"}


def test_gallery_recent(api):
    client, ctx = api
    ctx.history().record(JobMeta(source="gui", kind="template", title="x", template="datentraeger"),
                         landscape=None, head=None, length_mm=10.0, tape_mm=15.0, status="ok")
    r = client.get("/api/v1/gallery")
    assert "datentraeger" in r.json()["recent"]


def test_gallery_thumb(api, monkeypatch):
    client, ctx = api
    import tapesmith.webapi.routes_templates as rt

    calls = {"n": 0}
    original = rt.render_template

    def spy(*a, **kw):
        calls["n"] += 1
        return original(*a, **kw)

    monkeypatch.setattr(rt, "render_template", spy)

    r = client.get("/api/v1/gallery/thumb/datentraeger.png", params={"t": "test-token"})
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    image = Image.open(io.BytesIO(r.content))
    assert image.mode == "RGB"
    assert image.height == ctx.profile().head_dots
    assert calls["n"] == 1

    r2 = client.get("/api/v1/gallery/thumb/datentraeger.png", params={"t": "test-token"})
    assert r2.status_code == 200
    assert calls["n"] == 1  # aus dem Cache

    r3 = client.get("/api/v1/gallery/thumb/datentraeger.png",
                    params={"t": "test-token", "tape": "weiss-schwarz"})
    assert r3.status_code == 200
    assert r3.content != r.content


def test_gallery_thumb_render_error_is_404(api):
    client, _ = api
    r = client.get("/api/v1/gallery/thumb/gibtsnicht.png", params={"t": "test-token"})
    assert r.status_code == 404


def test_gallery_favorites(api):
    client, _ = api
    r = client.post("/api/v1/gallery/favorites/datentraeger", json={"favorite": True})
    assert r.status_code == 200
    assert "datentraeger" in r.json()["favorites"]
    cfg_path = paths.config_path()
    assert "datentraeger" in json.loads(cfg_path.read_text(encoding="utf-8"))["gui"]["favorites"]

    r2 = client.post("/api/v1/gallery/favorites/datentraeger", json={"favorite": True})
    assert r2.json()["favorites"] == r.json()["favorites"]

    r3 = client.post("/api/v1/gallery/favorites/datentraeger", json={"favorite": False})
    assert "datentraeger" not in r3.json()["favorites"]


# ================================================================ Import/Export


def test_export_import_package(api):
    client, _ = api
    r = client.post("/api/v1/templates/export", json={"names": ["datentraeger"]})
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    assert "vorlagen-" in r.headers["content-disposition"]

    package_b64 = base64.b64encode(r.content).decode("ascii")
    r2 = client.post("/api/v1/templates/import", json={"package_b64": package_b64, "overwrite": True})
    assert r2.status_code == 200
    assert r2.json()["imported"] == ["datentraeger"]


def test_export_unknown_template_is_404(api):
    client, _ = api
    r = client.post("/api/v1/templates/export", json={"names": ["gibtsnicht"]})
    assert r.status_code == 404


def test_parse_file(api):
    client, _ = api
    from importlib import resources

    raw = resources.files("tapesmith.templates.builtin").joinpath("datentraeger.tapesmith.json").read_bytes()
    data_b64 = base64.b64encode(raw).decode("ascii")
    r = client.post("/api/v1/templates/parse-file", json={"name": "datentraeger.tapesmith.json",
                                                           "data_b64": data_b64})
    assert r.status_code == 200
    assert r.json()["definition"]["name"] == "datentraeger"
    assert r.json()["name"] == "datentraeger"

    broken = base64.b64encode(b"{kaputt").decode("ascii")
    r2 = client.post("/api/v1/templates/parse-file", json={"name": "x.json", "data_b64": broken})
    assert r2.status_code == 422


# ================================================================ Lint (Routenreihenfolge)


def test_lint_route_not_shadowed_by_name_param(api):
    client, _ = api
    r = client.get("/api/v1/templates/lint")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["issues"], list)
    assert not any(issue["level"] == "error" for issue in body["issues"])


def test_fixed_routes_before_param_routes(api):
    """Jede feste Route mit gleich beginnendem Parametergegenstück: eigener Aufruf/Körpertyp."""
    client, _ = api
    assert client.get("/api/v1/templates/lint").json().get("issues") is not None
    assert client.post("/api/v1/templates/import",
                       json={"package_b64": "", "overwrite": False}).status_code == 422
    assert client.post("/api/v1/templates/export", json={"names": []}).status_code == 200
    assert client.post("/api/v1/templates/parse-file",
                       json={"name": "x", "data_b64": ""}).status_code == 422
    assert client.get("/api/v1/gallery").json().get("categories") is not None


# ================================================================ Raster-Belegung


def test_export_assignment_csv(api):
    client, _ = api
    r = client.post("/api/v1/templates/raster-patchpanel/assignment",
                    json={"values": {"belegung": "pmx10\npmx20\nNAS"}})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    text = r.content.decode("utf-8-sig")
    assert "Nr" in text.splitlines()[0]


def test_export_assignment_needs_raster(api):
    client, _ = api
    r = client.post("/api/v1/templates/datentraeger/assignment", json={"values": {}})
    assert r.status_code == 422


def test_detail_schriftgroesse_und_standard_platzhalter(api):
    client, _ = api
    body = client.get("/api/v1/templates/raster-patchpanel").json()
    by_id = {f["id"]: f for f in body["fields"]}
    size = by_id["schriftgroesse"]
    assert size["role"] == "text_size"
    assert size["default"] == "auto" and size["choices"][:2] == ["auto", "auto-feld"]
    assert by_id["raster_mm"]["default_hint"] == "15.875"
    assert by_id["belegung"]["default_hint"] is None and by_id["belegung"]["role"] is None
    assert "schriftgroesse" not in [f["id"] for f in body["input_fields"]]
    assert "schriftgroesse" not in [f["id"] for f in body["definition"]["fields"]]
    plain = client.get("/api/v1/templates/kabelfahne").json()
    assert all(f["role"] is None for f in plain["fields"])
