"""Router /homelab/plausi und /homelab/assets/{id}/vault-note."""

import threading
import time

import pytest

from homelab_fakes import mock_transport, router_client, write_homelab
from obsidian_fakes import FakeMcp
from tapesmith.integrations import settings
from tapesmith.integrations.assets import AssetStore
from tapesmith.sshscan import DiskRow
from tapesmith.webapi import routes_plausi
from webapi_fakes import close_ctx

# Integrationen im Produkt ohne Standardadressen: Tests nutzen neutrale Testadressen.
pytestmark = pytest.mark.usefixtures("homelab_test_defaults")


def _disk(host, device, serial):
    return DiskRow(host=host, device=device, model="Model X", serial=serial, size="1T", tran="sata",
                   wwn="", by_id=None, pool=None, vdev=None)


@pytest.fixture
def api(tmp_path):
    write_homelab({})
    client, ctx = router_client(tmp_path, routes_plausi.router,
                                extras={"resolver": lambda host: ["192.0.2.60"] if host == "pmx10" else []})
    yield client, ctx
    close_ctx(ctx)


def test_plausi_returns_findings_and_worst(api):
    from tapesmith.integrations import scancache

    client, _ctx = api
    scancache.save_scan("pmx20", [_disk("pmx20", "sdb", "ABC123DEF456")])
    response = client.post("/api/v1/homelab/plausi",
                           json={"template": "datentraeger", "values": {"host": "pmx10", "sn": "ABC123DEF456"},
                                 "vault": False})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["worst"] == "konflikt"
    codes = [f["code"] for f in body["findings"]]
    assert "sn_anderer_host" in codes
    assert body["findings"][0]["level"] == "konflikt"


def test_plausi_unknown_template_is_404(api):
    client, _ctx = api
    response = client.post("/api/v1/homelab/plausi", json={"template": "gibtsnicht", "values": {}, "vault": False})
    assert response.status_code == 404


def test_plausi_broken_asset_register_gives_info_not_500(api, tmp_path):
    client, _ctx = api
    path = settings.data_dir() / "assets.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"das ist keine sqlite-datei")
    response = client.post("/api/v1/homelab/plausi",
                           json={"template": "datentraeger", "values": {"sn": "X"}, "vault": False})
    assert response.status_code == 200, response.text
    codes = [f["code"] for f in response.json()["findings"]]
    assert "quelle_fehlt" in codes


def test_plausi_does_not_create_register_files(api):
    client, _ctx = api
    response = client.post("/api/v1/homelab/plausi",
                           json={"template": "datentraeger", "values": {"nummer": "HL-0001"}, "vault": False})
    assert response.status_code == 200, response.text
    assert not (settings.data_dir() / "assets.sqlite3").exists()
    assert not (settings.data_dir() / "kabel.json").exists()


def test_plausi_dns_uses_extras_resolver(api):
    client, _ctx = api
    response = client.post("/api/v1/homelab/plausi",
                           json={"template": "host-ip", "values": {"host": "pmx10", "ip": "192.0.2.61"},
                                 "vault": False})
    assert response.status_code == 200, response.text
    codes = [f["code"] for f in response.json()["findings"]]
    assert "dns_abweichung" in codes


def test_vault_note_creates_note_via_mcp(api):
    client, ctx = api
    with AssetStore() as store:
        store.add_existing("HL-0001", bezeichnung="Patchkabel", standort="Keller")
    written = {}
    fake = FakeMcp({"vault_write": lambda args: written.update(args) or "ok"})
    ctx.extras["transports"] = {"obsidian": fake.transport()}

    response = client.post("/api/v1/homelab/assets/HL-0001/vault-note")
    assert response.status_code == 200, response.text
    assert response.json()["path"] == "Assets/HL-0001"
    assert written["path"] == "Assets/HL-0001"
    assert written["overwrite"] is False


def test_vault_note_unknown_asset_is_404(api):
    client, ctx = api
    ctx.extras["transports"] = {"obsidian": mock_transport({})}
    response = client.post("/api/v1/homelab/assets/HL-9999/vault-note")
    assert response.status_code == 404


def test_vault_note_existing_note_is_409(api):
    client, ctx = api
    with AssetStore() as store:
        store.add_existing("HL-0002", bezeichnung="Test")

    def vault_write_conflict(request):
        import httpx
        body = request.content.decode("utf-8")
        import json as jsonlib
        message = jsonlib.loads(body)
        if message.get("method") == "tools/call" and message["params"]["name"] == "vault_write":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": message["id"],
                                             "result": {"content": [{"type": "text",
                                                                     "text": "Notiz existiert bereits"}],
                                                       "isError": True}})
        if message.get("method") == "initialize":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": message["id"],
                                             "result": {"protocolVersion": "2025-06-18"}})
        if message.get("method") == "notifications/initialized":
            return httpx.Response(202)
        raise AssertionError(f"unerwartete MCP-Methode {message.get('method')}")

    import httpx

    ctx.extras["transports"] = {"obsidian": httpx.MockTransport(vault_write_conflict)}
    response = client.post("/api/v1/homelab/assets/HL-0002/vault-note")
    assert response.status_code == 409, response.text


def test_timed_resolver_returns_within_timeout_even_if_resolver_hangs():
    """Ein hängender Resolver darf die Antwortzeit nicht über das Zeitlimit hinaus verzögern.

    Der Executor darf beim Verlassen von `_timed_resolver.call` nicht auf den (weiterhin
    laufenden) Resolver-Thread warten (kein `shutdown(wait=True)` via Context-Manager),
    sonst begrenzt der Timeout die Antwortzeit nicht wie verlangt.
    """

    release = threading.Event()

    def hanging_resolver(host: str) -> list[str]:
        release.wait(30)
        return ["should-not-be-seen"]

    timed = routes_plausi._timed_resolver(hanging_resolver, 0.5)

    start = time.monotonic()
    try:
        result = timed("pmx10")
    finally:
        release.set()
    elapsed = time.monotonic() - start

    assert result == []
    # Der Resolver hinge 30 s; die Grenze lässt langsamen Rechnern Luft und trennt trotzdem klar.
    assert elapsed < 10.0, f"_timed_resolver blockierte {elapsed:.2f}s, sollte nach ~0.5s zurückkehren"
