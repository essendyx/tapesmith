"""Editor-Operationen, Einrasten, Icons, Bildimport, Zielobjekte."""

import base64
import io

import pytest
from PIL import Image

from webapi_fakes import close_ctx, make_client

EMPTY_DOC = {"version": 1, "objects": []}


@pytest.fixture
def api(tmp_path):
    client, ctx = make_client(tmp_path)
    yield client, ctx
    close_ctx(ctx)


def _png_b64(size=(20, 20), color=0) -> str:
    img = Image.new("L", size, color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _doc(*objects) -> dict:
    return {"version": 1, "objects": list(objects)}


def _text(oid: str, x: int, y: int, w: int = 20, h: int = 20, text: str = "A") -> dict:
    return {"kind": "text", "id": oid, "x": x, "y": y, "w": w, "h": h, "text": text}


def test_new_object_text_on_empty_document(api):
    client, _ = api
    r = client.post("/api/v1/editor/new-object", json={"document": EMPTY_DOC, "preset": "text"})
    assert r.status_code == 200
    body = r.json()
    ids = [o["id"] for o in body["document"]["objects"]]
    assert len(ids) == 1
    assert ids[0].startswith("text")
    assert body["selected"] == ids
    assert body["step_label"] == "Text hinzugefügt"


def test_new_object_image_needs_png(api):
    client, _ = api
    r = client.post("/api/v1/editor/new-object", json={"document": EMPTY_DOC, "preset": "image"})
    assert r.status_code == 422

    img_r = client.post("/api/v1/editor/image", json={"data_b64": _png_b64()})
    assert img_r.status_code == 200
    img_body = img_r.json()
    assert img_body["width"] == 20
    assert img_body["height"] == 20

    r2 = client.post("/api/v1/editor/new-object",
                     json={"document": EMPTY_DOC, "preset": "image", "png": img_body["png"]})
    assert r2.status_code == 200
    assert r2.json()["document"]["objects"][0]["kind"] == "image"


def test_op_move_and_snap(api):
    client, _ = api
    doc = _doc(_text("text1", 0, 0))
    r = client.post("/api/v1/editor/op",
                    json={"document": doc, "op": "move", "ids": ["text1"], "params": {"dx": 8, "dy": 0}})
    assert r.status_code == 200
    body = r.json()
    assert body["document"]["objects"][0]["x"] == 8

    doc2 = _doc(_text("text1", 0, 0), _text("text2", 30, 0))
    r2 = client.post("/api/v1/editor/op",
                     json={"document": doc2, "op": "move", "ids": ["text2"],
                            "params": {"dx": -9, "dy": 0, "snap": True}})
    assert r2.status_code == 200
    body2 = r2.json()
    assert body2["guides"]
    obj2 = next(o for o in body2["document"]["objects"] if o["id"] == "text2")
    assert obj2["x"] == 20


def test_op_set_box_and_update(api):
    client, _ = api
    doc = _doc(_text("text1", 0, 0))
    r = client.post("/api/v1/editor/op",
                    json={"document": doc, "op": "set_box", "ids": ["text1"],
                           "params": {"x": 5, "y": 5, "w": 30, "h": 15}})
    assert r.status_code == 200
    obj = r.json()["document"]["objects"][0]
    assert (obj["x"], obj["y"], obj["w"], obj["h"]) == (5, 5, 30, 15)

    r2 = client.post("/api/v1/editor/op",
                     json={"document": doc, "op": "update", "ids": ["text1"],
                            "params": {"changes": {"text": "Neu"}}})
    assert r2.status_code == 200
    assert r2.json()["document"]["objects"][0]["text"] == "Neu"

    r3 = client.post("/api/v1/editor/op",
                     json={"document": doc, "op": "update", "ids": ["text1"],
                            "params": {"changes": {"gibtsnicht": 1}}})
    assert r3.status_code == 422


def test_op_align_and_distribute(api):
    client, _ = api
    doc = _doc(_text("text1", 0, 0), _text("text2", 40, 10))
    r = client.post("/api/v1/editor/op",
                    json={"document": doc, "op": "align", "ids": ["text1", "text2"],
                           "params": {"mode": "left", "reference": "selection"}})
    assert r.status_code == 200
    xs = {o["id"]: o["x"] for o in r.json()["document"]["objects"]}
    assert xs["text1"] == xs["text2"]

    doc3 = _doc(_text("text1", 0, 0, 10, 10), _text("text2", 20, 0, 10, 10), _text("text3", 60, 0, 10, 10))
    r2 = client.post("/api/v1/editor/op",
                     json={"document": doc3, "op": "distribute", "ids": ["text1", "text2", "text3"],
                            "params": {"axis": "h"}})
    assert r2.status_code == 200
    xs2 = {o["id"]: o["x"] for o in r2.json()["document"]["objects"]}
    assert xs2["text2"] == 30

    r3 = client.post("/api/v1/editor/op",
                     json={"document": doc, "op": "distribute", "ids": ["text1", "text2"],
                            "params": {"axis": "h"}})
    assert r3.status_code == 422


def test_op_reorder_rotate_flip_label_length(api):
    client, _ = api
    doc = _doc(_text("text1", 0, 0), _text("text2", 30, 0))
    r = client.post("/api/v1/editor/op",
                    json={"document": doc, "op": "reorder", "ids": ["text1"], "params": {"op": "top"}})
    assert r.status_code == 200
    ids_order = [o["id"] for o in r.json()["document"]["objects"]]
    assert ids_order[-1] == "text1"

    r2 = client.post("/api/v1/editor/op",
                     json={"document": doc, "op": "rotate", "ids": ["text1"], "params": {"degrees": 90}})
    assert r2.status_code == 200
    obj2 = next(o for o in r2.json()["document"]["objects"] if o["id"] == "text1")
    assert obj2["rotation"] == 90

    r3 = client.post("/api/v1/editor/op",
                     json={"document": doc, "op": "flip", "ids": ["text1"], "params": {}})
    assert r3.status_code == 200
    obj3 = next(o for o in r3.json()["document"]["objects"] if o["id"] == "text1")
    assert obj3["mirror"] is True

    r4 = client.post("/api/v1/editor/op",
                     json={"document": doc, "op": "label_transform", "ids": [], "params": {"mirror": True}})
    assert r4.status_code == 200
    assert r4.json()["document"]["mirror"] is True

    r5 = client.post("/api/v1/editor/op",
                     json={"document": doc, "op": "set_length", "ids": [],
                            "params": {"mode": "fixed", "length_mm": 30}})
    assert r5.status_code == 200
    assert r5.json()["document"]["length_mode"] == "fixed"
    assert r5.json()["document"]["length_mm"] == 30


def test_op_duplicate_remove_and_errors(api):
    client, _ = api
    doc = _doc(_text("text1", 0, 0))
    r = client.post("/api/v1/editor/op",
                    json={"document": doc, "op": "duplicate", "ids": ["text1"], "params": {}})
    assert r.status_code == 200
    body = r.json()
    assert len(body["document"]["objects"]) == 2
    assert body["selected"] != ["text1"]

    r2 = client.post("/api/v1/editor/op",
                     json={"document": doc, "op": "remove", "ids": ["text1"], "params": {}})
    assert r2.status_code == 200
    body2 = r2.json()
    assert body2["document"]["objects"] == []
    assert body2["selected"] == []

    r3 = client.post("/api/v1/editor/op",
                     json={"document": doc, "op": "keinsowas", "ids": [], "params": {}})
    assert r3.status_code == 422

    r4 = client.post("/api/v1/editor/op",
                     json={"document": {"objects": "kaputt"}, "op": "remove", "ids": [], "params": {}})
    assert r4.status_code == 422


def test_snap_resize(api):
    client, _ = api
    doc = _doc(_text("text1", 0, 0))
    r = client.post("/api/v1/editor/snap",
                    json={"document": doc, "ids": ["text1"], "dx": 5, "dy": 0, "mode": "resize",
                           "handle": "e"})
    assert r.status_code == 200
    body = r.json()
    assert "dx" in body and "dy" in body and "guides" in body

    r2 = client.post("/api/v1/editor/snap",
                     json={"document": doc, "ids": ["text1"], "dx": 5, "dy": 0, "mode": "resize",
                            "handle": "zz"})
    assert r2.status_code == 422


def test_icons_search_png_and_categories(api):
    client, _ = api
    r = client.get("/api/v1/icons", params={"query": "server"})
    assert r.status_code == 200
    icons = r.json()["icons"]
    assert icons
    assert any(i["ref"] == "tabler:server" for i in icons)

    r2 = client.get("/api/v1/icons/png", params={"ref": "tabler:server", "size": 48, "t": "test-token"})
    assert r2.status_code == 200
    assert r2.headers["content-type"] == "image/png"
    img = Image.open(io.BytesIO(r2.content))
    assert img.size == (48, 48)

    r3 = client.get("/api/v1/icons/png", params={"ref": "tabler:gibtsnicht"})
    assert r3.status_code == 404

    r4 = client.get("/api/v1/icons/categories")
    assert r4.status_code == 200
    assert r4.json()["categories"]


def test_icons_user_import(api):
    client, _ = api
    r = client.post("/api/v1/icons/user", json={"name": "Mein Icon", "data_b64": _png_b64()})
    assert r.status_code == 200
    assert r.json()["ref"].startswith("user:")


def test_targets(api):
    client, _ = api
    r = client.get("/api/v1/targets")
    assert r.status_code == 200
    targets = r.json()["targets"]
    assert targets
    assert "id" in targets[0] and "name" in targets[0]
