"""Windows-Integration (`/integration`), Aktionen (`/integration/resolve`,
`pending`). Registry ausschließlich über `FakeRegistry`."""

import base64
import io
import json
import urllib.parse

import pytest
from PIL import Image

from tapesmith import integration as intg
from tapesmith.webapi import actions
from webapi_fakes import close_ctx, make_client


@pytest.fixture
def registry():
    return intg.FakeRegistry()


@pytest.fixture
def api(tmp_path, registry):
    client, ctx = make_client(tmp_path, registry_factory=lambda: registry)
    yield client, ctx
    close_ctx(ctx)


# ---------- GET /integration, install/uninstall ----------

def test_integration_status_nicht_installiert(api):
    client, _ = api
    r = client.get("/api/v1/integration")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == {"context": "nicht installiert", "uri": "nicht installiert",
                              "autostart": "nicht installiert"}
    assert body["lines"] == []


def test_integration_install_dry_run_laesst_registry_leer(api, registry):
    client, _ = api
    r = client.post("/api/v1/integration/install",
                    json={"context": True, "uri": True, "autostart": False, "dry_run": True})
    assert r.status_code == 200
    body = r.json()
    assert body["lines"]
    assert registry.data == {}
    assert body["status"]["context"] == "nicht installiert"


def test_integration_install_und_uninstall(api, registry):
    client, _ = api
    r = client.post("/api/v1/integration/install",
                    json={"context": True, "uri": True, "autostart": False, "dry_run": False})
    assert r.status_code == 200
    body = r.json()
    assert body["status"]["context"] == "installiert"
    assert body["status"]["uri"] == "installiert"
    assert body["status"]["autostart"] == "nicht installiert"
    assert registry.data != {}

    r = client.post("/api/v1/integration/uninstall",
                    json={"context": True, "uri": True, "autostart": True, "dry_run": False})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == {"context": "nicht installiert", "uri": "nicht installiert",
                              "autostart": "nicht installiert"}


def test_integration_install_ohne_teil_ist_422(api):
    client, _ = api
    r = client.post("/api/v1/integration/install",
                    json={"context": False, "uri": False, "autostart": False, "dry_run": False})
    assert r.status_code == 422
    assert r.json()["error"]["message"] == "Bitte mindestens einen Teil wählen"


# ---------- resolve: URI ----------

def test_resolve_uri_template(api):
    client, _ = api
    r = client.post("/api/v1/integration/resolve",
                    json={"uri": "tapesmith://print?template=datentraeger&sn=274913"})
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "template"
    assert body["route"].startswith("/vorlagen?vorlage=datentraeger&werte=")
    query = urllib.parse.urlsplit(body["route"]).query
    params = urllib.parse.parse_qs(query)
    values = json.loads(params["werte"][0])
    assert values["sn"] == "274913"


def test_resolve_uri_ungueltig_422(api):
    client, _ = api
    r = client.post("/api/v1/integration/resolve", json={"uri": "http://etwas-anderes"})
    assert r.status_code == 422


def test_resolve_weder_uri_noch_open_422(api):
    client, _ = api
    r = client.post("/api/v1/integration/resolve", json={})
    assert r.status_code == 422


# ---------- resolve: open=lines ----------

def test_resolve_open_lines_kurz(api, tmp_path):
    client, _ = api
    path = tmp_path / "zeilen.txt"
    path.write_text("eins\nzwei\n", encoding="utf-8")
    r = client.post("/api/v1/integration/resolve", json={"open": "lines", "path": str(path)})
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "lines"
    assert body["route"].startswith("/schnelldruck?text=")
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(body["route"]).query)
    assert query["text"][0] == "eins\nzwei"


def test_resolve_open_lines_lang_wird_pending(api, tmp_path):
    client, _ = api
    lines = [f"zeile{i}" for i in range(5)]
    path = tmp_path / "zeilen.txt"
    path.write_text("\n".join(lines), encoding="utf-8")
    r = client.post("/api/v1/integration/resolve", json={"open": "lines", "path": str(path)})
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "lines"
    assert body["route"].startswith("/vorlagen?import=")
    pending_id = body["route"].rsplit("=", 1)[1]

    r2 = client.get(f"/api/v1/integration/pending/{pending_id}")
    assert r2.status_code == 200
    entry = r2.json()
    assert entry["type"] == "lines"
    assert entry["lines"] == lines


# ---------- resolve: open=batch ----------

def test_resolve_open_batch_csv(api, tmp_path):
    client, _ = api
    path = tmp_path / "daten.csv"
    path.write_text("name;wert\nA;1\nB;2\n", encoding="utf-8")
    r = client.post("/api/v1/integration/resolve", json={"open": "batch", "path": str(path)})
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "batch"
    pending_id = body["route"].rsplit("=", 1)[1]
    entry = client.get(f"/api/v1/integration/pending/{pending_id}").json()
    assert entry["type"] == "table"
    assert entry["headers"] == ["name", "wert"]
    assert entry["rows"] == [["A", "1"], ["B", "2"]]
    assert entry["source_name"] == "daten.csv"


# ---------- resolve: open=image ----------

def test_resolve_open_image(api, tmp_path):
    client, _ = api
    path = tmp_path / "bild.png"
    Image.new("RGB", (4, 3), (255, 0, 0)).save(path)
    r = client.post("/api/v1/integration/resolve", json={"open": "image", "path": str(path)})
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "image"
    pending_id = body["route"].rsplit("=", 1)[1]
    entry = client.get(f"/api/v1/integration/pending/{pending_id}").json()
    assert entry["type"] == "image"
    assert entry["name"] == "bild.png"
    decoded = base64.b64decode(entry["data_b64"])
    img = Image.open(io.BytesIO(decoded))
    assert img.format == "PNG"
    assert img.size == (4, 3)


def test_resolve_open_image_zu_gross_422(api, tmp_path, monkeypatch):
    client, _ = api
    path = tmp_path / "bild.png"
    Image.new("RGB", (4, 3), (0, 0, 0)).save(path)
    monkeypatch.setattr(actions, "MAX_IMAGE_BYTES", 4)
    r = client.post("/api/v1/integration/resolve", json={"open": "image", "path": str(path)})
    assert r.status_code == 422


# ---------- resolve: open=template ----------

def test_resolve_open_template(api, tmp_path):
    client, _ = api
    path = tmp_path / "meine.tapesmith.json"
    definition = {
        "schema_version": 2, "name": "meine", "description": "",
        "fields": [{"id": "host", "label": "Host", "type": "input"}],
        "document": {"version": 1, "objects": [
            {"kind": "text", "id": "t1", "x": 0, "y": 0, "w": 200, "h": 40, "text": "{host}"},
        ]},
    }
    path.write_text(json.dumps(definition), encoding="utf-8")
    r = client.post("/api/v1/integration/resolve", json={"open": "template", "path": str(path)})
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "template"
    assert body["route"].startswith("/vorlagen?datei=")
    pending_id = body["route"].rsplit("=", 1)[1]
    entry = client.get(f"/api/v1/integration/pending/{pending_id}").json()
    assert entry["type"] == "template_file"
    assert entry["name"] == "meine.tapesmith.json"
    assert entry["definition"]["name"] == "meine"


# ---------- resolve: open=folder-qr ----------

def test_resolve_open_folder_qr(api, tmp_path):
    client, _ = api
    r = client.post("/api/v1/integration/resolve", json={"open": "folder-qr", "path": str(tmp_path)})
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "qr"
    assert body["route"].startswith("/qr?inhalt=")
    assert body["note"] != ""


# ---------- Grenzfälle ----------

def test_resolve_unbekannte_pending_id_404(api):
    client, _ = api
    r = client.get("/api/v1/integration/pending/unbekannt")
    assert r.status_code == 404


def test_put_pending_verdraengt_aeltesten(tmp_path):
    client, ctx = make_client(tmp_path)
    try:
        ids = [actions.put_pending(ctx, {"type": "lines", "lines": [str(i)]}) for i in range(21)]
        store = ctx.extras[actions.PENDING_KEY]
        assert len(store) == actions.PENDING_MAX
        assert ids[0] not in store
        assert ids[-1] in store
    finally:
        close_ctx(ctx)
