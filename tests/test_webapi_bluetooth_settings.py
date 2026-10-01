"""POST /api/v1/system/open-bluetooth-settings: Windows-Bluetooth-Einstellungen öffnen."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tapesmith.webapi.access import LanPolicy
from webapi_fakes import close_ctx, make_client, make_token

URL = "/api/v1/system/open-bluetooth-settings"
LAN = LanPolicy(enabled=True, networks=("192.0.2.0/24",), hosts=frozenset({"192.0.2.50"}))


def test_oeffnet_einstellungen_am_pc(tmp_path):
    opened = []
    client, ctx = make_client(tmp_path, uri_opener=opened.append)
    try:
        r = client.post(URL)
        assert r.status_code == 200, r.text
        assert opened == ["ms-settings:bluetooth"]
    finally:
        close_ctx(ctx)


def test_andere_rolle_und_lan_verboten(tmp_path):
    opened = []
    client, ctx = make_client(tmp_path, lan=LAN, uri_opener=opened.append)
    try:
        printer = make_token(ctx, "drucken")
        assert client.post(URL, headers={"Authorization": f"Bearer {printer}"}).status_code == 403
        admin = make_token(ctx, "admin")
        lan = TestClient(client.app, base_url="http://192.0.2.50:8712",
                         headers={"Authorization": f"Bearer {admin}"}, client=("192.0.2.77", 50124))
        assert lan.post(URL).status_code == 403
        assert opened == []
    finally:
        close_ctx(ctx)
