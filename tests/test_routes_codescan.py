"""Route POST /api/v1/homelab/codescan."""

import base64
from io import BytesIO

import zxingcpp
from PIL import Image

from homelab_fakes import router_client
from tapesmith.integrations.codescan import MAX_BYTES
from tapesmith.webapi import routes_codescan
from webapi_fakes import close_ctx


def _code128_png(text: str) -> bytes:
    barcode = zxingcpp.create_barcode(text, zxingcpp.BarcodeFormat.Code128)
    img = barcode.to_image(scale=3, add_quiet_zones=True)
    mv = memoryview(img)
    rows, cols = mv.shape
    pil = Image.frombytes("L", (cols, rows), bytes(mv)).convert("RGB")
    canvas = Image.new("RGB", (pil.width + 40, pil.height + 40), (255, 255, 255))
    canvas.paste(pil, (20, 20))
    buf = BytesIO()
    canvas.save(buf, format="PNG")
    return buf.getvalue()


def test_post_codescan_returns_best_and_shortened(tmp_path):
    client, ctx = router_client(tmp_path, routes_codescan.router)
    try:
        image_b64 = base64.b64encode(_code128_png("S/N ABC123456")).decode("ascii")
        response = client.post("/api/v1/homelab/codescan", json={"image_b64": image_b64})
    finally:
        close_ctx(ctx)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["best"] == "ABC123456"
    assert body["shortened"] == "123456"
    assert body["width"] > 0 and body["height"] > 0
    assert any(h["text"] == "S/N ABC123456" for h in body["hits"])


def test_post_codescan_tolerates_data_uri_prefix(tmp_path):
    client, ctx = router_client(tmp_path, routes_codescan.router)
    try:
        image_b64 = base64.b64encode(_code128_png("S/N WITHPREFIX99")).decode("ascii")
        response = client.post(
            "/api/v1/homelab/codescan", json={"image_b64": f"data:image/png;base64,{image_b64}"}
        )
    finally:
        close_ctx(ctx)
    assert response.status_code == 200, response.text
    assert response.json()["best"] == "WITHPREFIX99"


def test_post_codescan_invalid_base64_is_422(tmp_path):
    client, ctx = router_client(tmp_path, routes_codescan.router)
    try:
        response = client.post("/api/v1/homelab/codescan", json={"image_b64": "not-base64!!"})
    finally:
        close_ctx(ctx)
    assert response.status_code == 422
    assert "error" in response.json()


def test_post_codescan_too_large_is_422(tmp_path):
    client, ctx = router_client(tmp_path, routes_codescan.router)
    try:
        huge = base64.b64encode(b"x" * (MAX_BYTES + 1)).decode("ascii")
        response = client.post("/api/v1/homelab/codescan", json={"image_b64": huge})
    finally:
        close_ctx(ctx)
    assert response.status_code == 422


def test_post_codescan_no_codes_returns_null_best(tmp_path):
    client, ctx = router_client(tmp_path, routes_codescan.router)
    try:
        canvas = Image.new("RGB", (200, 100), (255, 255, 255))
        buf = BytesIO()
        canvas.save(buf, format="PNG")
        image_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        response = client.post("/api/v1/homelab/codescan", json={"image_b64": image_b64})
    finally:
        close_ctx(ctx)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["best"] is None
    assert body["shortened"] is None
    assert body["hits"] == []
