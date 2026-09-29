"""Routen /api/v1/homelab/vault. MCP nur als Fake über MockTransport."""

import base64
import io
from datetime import datetime

import pytest
from PIL import Image, ImageDraw

from homelab_fakes import connect_error_transport, router_client, write_homelab
from obsidian_fakes import FakeMcp, vault_tools
from tapesmith.jobs import JobMeta
from tapesmith.webapi import batchapi, routes_vault
from webapi_fakes import close_ctx

# Integrationen im Produkt ohne Standardadressen: Tests nutzen neutrale Testadressen.
pytestmark = pytest.mark.usefixtures("homelab_test_defaults")

NOW = datetime(2026, 9, 28, 9, 30, 0)


@pytest.fixture
def api(tmp_path):
    fake = FakeMcp(vault_tools())
    client, ctx = router_client(tmp_path, routes_vault.router,
                                extras={"transports": {"obsidian": fake.transport()}}, now=lambda: NOW)
    yield client, ctx, fake
    close_ctx(ctx)


def _record(ctx, *, head=True) -> int:
    image = Image.new("1", (ctx.profile().head_dots, 50), 255)
    ImageDraw.Draw(image).rectangle((10, 10, 60, 30), fill=0)
    meta = JobMeta(source="api", kind="template", title="Datenträger", template="datentraeger",
                   values={"host": "pmx30", "slot": "SSD-1", "sn": "111111274913"})
    return ctx.history().record(meta, landscape=None, head=image if head else None, length_mm=20.0,
                                tape_mm=12.0, status="ok")


def test_notes_without_folder_queries_configured_folders(api):
    client, _ctx, fake = api
    response = client.get("/api/v1/homelab/vault/notes")
    assert response.status_code == 200, response.text
    assert response.json() == {"folders": ["Hosts", "Dienste"], "notes": ["Hosts/pmx30", "Dienste/testdienst"]}
    assert fake.tool_calls == [("vault_list", {"folder": "Hosts"}), ("vault_list", {"folder": "Dienste"})]


def test_notes_with_folder_and_forbidden_folder(api):
    client, _ctx, fake = api
    assert client.get("/api/v1/homelab/vault/notes", params={"folder": "Dienste"}).json()["notes"] == [
        "Dienste/testdienst"]
    response = client.get("/api/v1/homelab/vault/notes", params={"folder": "Privat"})
    assert response.status_code == 422
    assert len(fake.tool_calls) == 1


def test_note_values_and_tables(api):
    client, _ctx, _fake = api
    response = client.get("/api/v1/homelab/vault/note", params={"path": "Hosts/pmx30"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["path"] == "Hosts/pmx30" and body["title"] == "pmx30"
    assert body["values"]["ip"] == "192.0.2.99"
    assert "text" not in body
    assert body["tables"][0] == {"heading": "Platten", "headers": ["Label", "Seriennummer", "Rolle"],
                                 "rows": [["SSD-1", "111111274913", "rpool Spiegel"],
                                          ["SSD-2", "222222274988", "rpool Spiegel"]]}


def test_note_outside_folders_is_422_without_request(api):
    client, _ctx, fake = api
    response = client.get("/api/v1/homelab/vault/note", params={"path": "Privat/x"})
    assert response.status_code == 422
    assert "außerhalb der freigegebenen Ordner" in response.json()["error"]["message"]
    assert fake.requests == []


def test_table_creates_pending(api):
    client, ctx, _fake = api
    response = client.post("/api/v1/homelab/vault/table", json={"path": "Hosts/pmx30", "table": 0})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["count"] == 2 and body["headers"] == ["label", "seriennummer", "rolle"]
    table = batchapi.load_source(ctx, {"type": "pending", "id": body["pending_id"]})
    assert table.headers == ("label", "seriennummer", "rolle")
    assert table.rows[0] == ("SSD-1", "111111274913", "rpool Spiegel")

    response = client.post("/api/v1/homelab/vault/table",
                           json={"path": "Hosts/pmx30", "table": 0, "columns": {"Seriennummer": "sn"},
                                 "template": "datentraeger"})
    body = response.json()
    assert body["headers"] == ["sn"]
    table = batchapi.load_source(ctx, {"type": "pending", "id": body["pending_id"]})
    assert table.headers == ("sn",)
    assert table.rows == (("111111274913",), ("222222274988",))


def test_table_errors(api):
    client, _ctx, _fake = api
    assert client.post("/api/v1/homelab/vault/table", json={"path": "Hosts/pmx30", "table": 5}).status_code == 422
    response = client.post("/api/v1/homelab/vault/table",
                           json={"path": "Hosts/pmx30", "table": 0, "columns": {"Fehlt": "x"}})
    assert response.status_code == 422


def test_printed_switch_on_appends(api):
    client, ctx, fake = api
    write_homelab({"obsidian": {"append_after_print": True}})
    entry_id = _record(ctx)
    response = client.post("/api/v1/homelab/vault/printed", json={"path": "Hosts/pmx30", "history_id": entry_id})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body == {"appended": True, "line": "- 2026-09-28 Label gedruckt: pmx30 · SSD-1 · SN 274913",
                    "saved_path": None, "reason": ""}
    assert fake.tool_calls == [("vault_append", {"path": "Hosts/pmx30",
                                                 "content": "\n- 2026-09-28 Label gedruckt: pmx30 · SSD-1 · SN 274913"})]


def test_printed_switch_off_and_force(api):
    client, ctx, fake = api
    entry_id = _record(ctx)
    response = client.post("/api/v1/homelab/vault/printed", json={"path": "Hosts/pmx30", "history_id": entry_id})
    assert response.status_code == 200
    assert response.json() == {"appended": False, "line": None, "saved_path": None, "reason": "ausgeschaltet"}
    assert fake.requests == []
    response = client.post("/api/v1/homelab/vault/printed",
                           json={"path": "Hosts/pmx30", "summary": "pmx30 · 192.0.2.99", "force": True})
    assert response.json()["appended"] is True
    assert fake.tool_calls == [("vault_append", {"path": "Hosts/pmx30",
                                                 "content": "\n- 2026-09-28 Label gedruckt: pmx30 · 192.0.2.99"})]


def test_printed_with_vault_dir_saves_png(api, tmp_path):
    client, ctx, fake = api
    write_homelab({"obsidian": {"append_after_print": True, "vault_dir": str(tmp_path / "vault")}})
    entry_id = _record(ctx)
    body = client.post("/api/v1/homelab/vault/printed", json={"path": "Hosts/pmx30", "history_id": entry_id}).json()
    assert body["appended"] is True
    assert body["line"].endswith(".png]]")
    assert (tmp_path / "vault" / "Anhänge" / "Labels").is_dir()
    assert body["saved_path"] and body["saved_path"].endswith(".png")


def test_printed_errors(api):
    client, _ctx, fake = api
    write_homelab({"obsidian": {"append_after_print": True}})
    response = client.post("/api/v1/homelab/vault/printed", json={"path": "Privat/x", "summary": "x"})
    assert response.status_code == 422
    response = client.post("/api/v1/homelab/vault/printed", json={"path": "Hosts/pmx30"})
    assert response.status_code == 422
    assert "summary oder history_id nötig" in response.json()["error"]["message"]
    assert client.post("/api/v1/homelab/vault/printed",
                       json={"path": "Hosts/pmx30", "history_id": 999}).status_code == 404
    assert fake.requests == []


def test_snippet_basic(api):
    client, ctx, fake = api
    entry_id = _record(ctx)
    response = client.post("/api/v1/homelab/vault/snippet", json={"history_id": None, "save_attachment": False,
                                                                 "append_to": None})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["history_id"] == entry_id
    image = Image.open(io.BytesIO(base64.b64decode(body["png"])))
    assert image.mode == "1"
    assert body["markdown"].startswith(f"- {datetime.now():%Y-%m-%d} Label gedruckt: pmx30 · SSD-1 · SN 274913 ![[label-")
    assert body["changelog_md"] == f"- Label gedruckt: pmx30 · SSD-1 · SN 274913 (Verlauf #{entry_id})"
    assert body["saved_path"] is None and body["appended"] is False and body["warnings"] == []
    assert fake.requests == []


def test_snippet_save_attachment(api, tmp_path):
    client, ctx, _fake = api
    entry_id = _record(ctx)
    body = client.post("/api/v1/homelab/vault/snippet",
                       json={"history_id": entry_id, "save_attachment": True}).json()
    assert body["saved_path"] is None
    assert body["warnings"] == [routes_vault.NO_VAULT_DIR_WARNING]

    write_homelab({"obsidian": {"vault_dir": str(tmp_path / "vault")}})
    body = client.post("/api/v1/homelab/vault/snippet",
                       json={"history_id": entry_id, "save_attachment": True}).json()
    saved = tmp_path / "vault" / "Anhänge" / "Labels" / body["file_name"]
    assert body["saved_path"] == str(saved) and saved.is_file()
    again = client.post("/api/v1/homelab/vault/snippet",
                        json={"history_id": entry_id, "save_attachment": True}).json()
    assert again["file_name"].endswith("-2.png")
    assert again["markdown"].endswith(f"![[{again['file_name']}]]")


def test_snippet_append_to(api):
    client, ctx, fake = api
    _record(ctx)
    response = client.post("/api/v1/homelab/vault/snippet", json={"append_to": "../x"})
    assert response.status_code == 422
    assert fake.requests == []
    body = client.post("/api/v1/homelab/vault/snippet", json={"append_to": "Hosts/pmx30"}).json()
    assert body["appended"] is True
    assert fake.tool_calls == [("vault_append", {"path": "Hosts/pmx30", "content": "\n" + body["markdown"]})]


def test_snippet_without_history_is_422(api):
    client, _ctx, _fake = api
    response = client.post("/api/v1/homelab/vault/snippet", json={})
    assert response.status_code == 422
    assert "Kein gedrucktes Label" in response.json()["error"]["message"]


def test_append_and_changelog(api):
    client, _ctx, fake = api
    assert client.post("/api/v1/homelab/vault/append",
                       json={"path": "Dienste/testdienst", "line": "- Notiz"}).json() == {"ok": True}
    assert client.post("/api/v1/homelab/vault/append", json={"path": "Hosts/x", "line": "a\nb"}).status_code == 422
    assert client.post("/api/v1/homelab/vault/append",
                       json={"path": "Hosts/x", "line": "x" * 501}).status_code == 422
    assert client.post("/api/v1/homelab/vault/append", json={"path": "Privat/x", "line": "a"}).status_code == 422
    assert client.post("/api/v1/homelab/vault/changelog",
                       json={"title": "Label gedruckt", "entry": "- x"}).json() == {"ok": True}
    assert client.post("/api/v1/homelab/vault/changelog", json={"title": "", "entry": "x"}).status_code == 422
    assert client.post("/api/v1/homelab/vault/changelog",
                       json={"title": "t", "entry": "x" * 4001}).status_code == 422
    assert fake.tool_calls == [("vault_append", {"path": "Dienste/testdienst", "content": "\n- Notiz"}),
                               ("changelog_add", {"title": "Label gedruckt", "entry": "- x", "date": ""})]


def test_not_reachable_is_503(tmp_path):
    client, ctx = router_client(tmp_path, routes_vault.router,
                                extras={"transports": {"obsidian": connect_error_transport()}})
    try:
        response = client.get("/api/v1/homelab/vault/notes")
    finally:
        close_ctx(ctx)
    assert response.status_code == 503
    assert response.json()["error"]["kind"] == "NotReachable"
