"""Ende-zu-Ende-Tests über `create_app` mit echter Sicherheits-Middleware.

Alle Homelab-Routen hängen unter `/api/v1/homelab` und brauchen das Sitzungs-Token. Kein Test nutzt
Netz: jeder Dienst bekommt einen `httpx.MockTransport`, ein Wächter verbietet echte Transporte und
DNS-Auflösung. Der Kurz-Link-Dienst aus `deploy/shortlink/` läuft über einen TestClient, den ein
MockTransport anbindet.
"""

from __future__ import annotations

import socket
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.routing import Match, Route

from homelab_fakes import FakeKeyring, connect_error_transport, load_json, mock_transport, token_file, write_homelab
from tapesmith import paths
from tapesmith.cli import main as cli_main
from tapesmith.cli_cmds import disks as disks_cmd
from tapesmith.integrations import scancache
from tapesmith.webapi import homelab_routers
from tapesmith.webapi.app import API_PREFIX, create_app
from webapi_fakes import BASE_URL, TOKEN, close_ctx, make_ctx, make_token

sys.path.insert(0, str(Path(__file__).parents[1] / "deploy" / "shortlink"))
import shortlink as shortlink_service  # noqa: E402

# Integrationen im Produkt ohne Standardadressen: Tests nutzen neutrale Testadressen.
pytestmark = pytest.mark.usefixtures("homelab_test_defaults")

SSH_DATA = Path(__file__).parent / "data" / "ssh"
HOMELAB = f"{API_PREFIX}/homelab"
ADMIN_TOKEN = "x" * 32

# Alle Homelab-Routen (45 Paare). Pfadparameter mit Beispielwerten.
E_ROUTES = [
    ("GET", "/homelab/settings"),
    ("PATCH", "/homelab/settings"),
    ("GET", "/homelab/check"),
    ("POST", "/homelab/zfs/scan"),
    ("POST", "/homelab/zfs/plan"),
    ("GET", "/homelab/proxmox/hosts"),
    ("POST", "/homelab/proxmox/guests"),
    ("POST", "/homelab/proxmox/table"),
    ("GET", "/homelab/paperless/asn/next"),
    ("POST", "/homelab/paperless/asn/reserve"),
    ("POST", "/homelab/paperless/asn/void"),
    ("GET", "/homelab/paperless/documents"),
    ("GET", "/homelab/paperless/documents/17/warranty"),
    ("GET", "/homelab/vault/notes"),
    ("GET", "/homelab/vault/note"),
    ("POST", "/homelab/vault/table"),
    ("POST", "/homelab/vault/snippet"),
    ("POST", "/homelab/vault/append"),
    ("POST", "/homelab/vault/printed"),
    ("POST", "/homelab/vault/changelog"),
    ("GET", "/homelab/assets"),
    ("POST", "/homelab/assets"),
    ("POST", "/homelab/assets/import"),
    ("PUT", "/homelab/assets/HL-0001"),
    ("POST", "/homelab/assets/HL-0001/void"),
    ("GET", "/homelab/assets/HL-0001/label"),
    ("POST", "/homelab/assets/table"),
    ("GET", "/homelab/assets/export.csv"),
    ("GET", "/homelab/ka"),
    ("POST", "/homelab/ka"),
    ("PUT", "/homelab/ka/KA-001"),
    ("POST", "/homelab/ka/KA-001/status"),
    ("GET", "/homelab/ka/KA-001/label"),
    ("POST", "/homelab/kabel/netbox"),
    ("POST", "/homelab/kabel/ids"),
    ("POST", "/homelab/kabel/table"),
    ("GET", "/homelab/kabel/register"),
    ("DELETE", "/homelab/kabel/register/K-001"),
    ("GET", "/homelab/ha/batteries"),
    ("PUT", "/homelab/ha/battery-type"),
    ("POST", "/homelab/ha/table"),
    ("POST", "/homelab/ha/todo"),
    ("POST", "/homelab/codescan"),
    ("POST", "/homelab/plausi"),
    ("POST", "/homelab/assets/HL-0001/vault-note"),
]


# ---------------------------------------------------------------- Hilfen

@pytest.fixture(autouse=True)
def kein_netz(monkeypatch):
    """Wächter: echte httpx-Transporte und DNS-Auflösung sind in diesen Tests verboten."""

    def no_transport(self, request):
        raise AssertionError(f"echter HTTP-Transport benutzt: {request.method} {request.url}")

    def no_dns(*args, **kwargs):
        raise AssertionError(f"echte DNS-Auflösung benutzt: {args!r}")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", no_transport)
    monkeypatch.setattr(socket, "getaddrinfo", no_dns)


def _fake_ssh_stdout() -> str:
    lsblk = (SSH_DATA / "pmx10-lsblk.json").read_text(encoding="utf-8")
    byid = (SSH_DATA / "pmx10-byid.txt").read_text(encoding="utf-8")
    zpool = (SSH_DATA / "pmx10-zpool.txt").read_text(encoding="utf-8")
    return lsblk + "\n@@BYID@@\n" + byid + "\n@@ZPOOL@@\n" + zpool


def _ssh_config(tmp_path) -> dict:
    key = tmp_path / "id_test_key"
    key.write_text("dummy-key", encoding="utf-8")
    return {"ssh": {"hosts": [{"name": "pmx10", "host": "192.0.2.60", "user": "root", "port": 22,
                               "key": str(key)}],
                    "timeout_s": 5, "strict_host_key": True}}


def _ssh_runner(argv, timeout):
    return 0, _fake_ssh_stdout(), ""


def _all_transports(**overrides) -> dict:
    transports = {name: mock_transport({}) for name in
                  ("paperless", "proxmox", "obsidian", "homeassistant", "shortlink")}
    transports.update(overrides)
    return transports


def _make(tmp_path, *, transports: dict | None = None, token: bool = True, config: dict | None = None):
    ctx = make_ctx(tmp_path, config=config if config is not None else _ssh_config(tmp_path),
                   ssh_runner=_ssh_runner)
    ctx.extras.update({"transports": transports if transports is not None else _all_transports(),
                       "keyring_module": FakeKeyring(),
                       "resolver": lambda host: []})
    headers = {"X-P12-Token": TOKEN} if token else {}
    return TestClient(create_app(ctx), base_url=BASE_URL, headers=headers, client=("127.0.0.1", 50123)), ctx


@pytest.fixture
def e2e(tmp_path):
    write_homelab({"paperless": {"token_ref": token_file(tmp_path, "paperless")},
                   "homeassistant": {"token_ref": token_file(tmp_path, "ha")},
                   "shortlink": {"token_ref": token_file(tmp_path, "shortlink", ADMIN_TOKEN)}})
    client, ctx = _make(tmp_path)
    yield client, ctx
    close_ctx(ctx)


def _flat_routes(app) -> list[Route]:
    """Alle Routen der App mit vollem Pfad (FastAPI hängt eingebundene Router verzögert ein,
    `app.routes` enthält dann Platzhalter; `iter_route_contexts` löst sie auf)."""
    try:
        from fastapi.routing import iter_route_contexts
    except ImportError:  # ältere FastAPI: app.routes ist schon flach
        contexts = app.routes
    else:
        contexts = iter_route_contexts(app.routes)
    flat = []
    for ctx in contexts:
        path, methods = getattr(ctx, "path", None), getattr(ctx, "methods", None)
        if path and methods:
            flat.append(Route(path, endpoint=_dummy, methods=sorted(methods)))
    return flat


def _dummy(request):  # pragma: no cover, Endpunkt wird nie aufgerufen
    raise AssertionError


def _homelab_routes(app) -> list[Route]:
    return [r for r in _flat_routes(app) if r.path.startswith(HOMELAB)]


def _scope(method: str, path: str) -> dict:
    return {"type": "http", "method": method, "path": path, "root_path": "", "headers": [],
            "query_string": b""}


def _full_matches(routes, method: str, path: str) -> list[Route]:
    return [r for r in routes if r.matches(_scope(method, path))[0] == Match.FULL]


def _call(client: TestClient, method: str, path: str, **kw) -> httpx.Response:
    return client.request(method, path, **kw)


# ---------------------------------------------------------------- Verdrahtung

def test_router_liste_vollstaendig():
    assert len(homelab_routers.routers()) == len(homelab_routers.ROUTER_MODULES) == 11


def test_jede_e_route_hat_genau_eine_passende_route(e2e):
    client, _ctx = e2e
    routes = _homelab_routes(client.app)
    for method, path in E_ROUTES:
        matches = _full_matches(routes, method, API_PREFIX + path)
        assert len(matches) == 1, f"{method} {path}: {[m.path for m in matches]}"


def test_keine_undokumentierten_homelab_routen(e2e):
    client, _ctx = e2e
    routes = _homelab_routes(client.app)
    covered = set()
    for method, path in E_ROUTES:
        for route in _full_matches(routes, method, API_PREFIX + path):
            covered.add((method, route.path))
    declared = {(m, r.path) for r in routes for m in r.methods if m != "HEAD"}
    assert declared - covered == set()
    assert len(declared) == len(E_ROUTES) == 45


def test_keine_doppelten_methode_pfad_paare(e2e):
    client, _ctx = e2e
    routes = _flat_routes(client.app)
    assert len(routes) > 45
    pairs = [(m, r.path) for r in routes for m in r.methods if m != "HEAD"]
    duplicates = {p for p in pairs if pairs.count(p) > 1}
    assert duplicates == set()


def test_ohne_token_jede_homelab_route_401(tmp_path):
    write_homelab({})
    client, ctx = _make(tmp_path, token=False)
    try:
        for method, path in E_ROUTES:
            response = _call(client, method, API_PREFIX + path, json={})
            assert response.status_code == 401, f"{method} {path}: {response.status_code}"
    finally:
        close_ctx(ctx)


def test_mit_token_jede_homelab_route_erreichbar(e2e):
    client, _ctx = e2e
    for method, path in E_ROUTES:
        kwargs = {} if method in ("GET", "DELETE") else {"json": {}}
        response = _call(client, method, API_PREFIX + path, **kwargs)
        assert response.status_code not in (401, 403, 405), f"{method} {path}: {response.status_code}"
        assert response.status_code < 500 or response.status_code in (502, 503), \
            f"{method} {path}: {response.status_code} {response.text[:300]}"
        if response.status_code == 404:
            assert response.json()["error"]["message"] != "Nicht gefunden", f"{method} {path} ohne Route"


# ---------------------------------------------------------------- Rollen (Rechteprüfung)

def _role_client(ctx, secret: str) -> TestClient:
    return TestClient(create_app(ctx), base_url=BASE_URL, headers={"Authorization": f"Bearer {secret}"},
                      client=("127.0.0.1", 50123))


@pytest.mark.parametrize("role", ["familie", "drucken"])
def test_familie_und_drucken_duerfen_keine_homelab_route(app_home, tmp_path, role):
    write_homelab({})
    client, ctx = _make(tmp_path)
    try:
        role_client = _role_client(ctx, make_token(ctx, role))
        for method, path in E_ROUTES:
            response = _call(role_client, method, API_PREFIX + path, json={})
            assert response.status_code == 403, f"{role} {method} {path}: {response.status_code}"
    finally:
        close_ctx(ctx)


def test_admin_token_erreicht_jede_homelab_route(app_home, tmp_path):
    write_homelab({"paperless": {"token_ref": token_file(tmp_path, "paperless")},
                   "homeassistant": {"token_ref": token_file(tmp_path, "ha")},
                   "shortlink": {"token_ref": token_file(tmp_path, "shortlink", ADMIN_TOKEN)}})
    client, ctx = _make(tmp_path)
    try:
        admin = _role_client(ctx, make_token(ctx, "admin"))
        for method, path in E_ROUTES:
            kwargs = {} if method in ("GET", "DELETE") else {"json": {}}
            response = _call(admin, method, API_PREFIX + path, **kwargs)
            assert response.status_code not in (401, 403, 405), f"{method} {path}: {response.status_code}"
    finally:
        close_ctx(ctx)


def test_drucken_behaelt_druck_endpunkte_familie_nicht(app_home, tmp_path):
    write_homelab({})
    client, ctx = _make(tmp_path)
    try:
        body = {"source": {"kind": "text", "text": "Hallo"}}
        drucken = _role_client(ctx, make_token(ctx, "drucken"))
        assert drucken.post(f"{API_PREFIX}/labels/render", json=body).status_code not in (401, 403)
        assert drucken.get(f"{API_PREFIX}/templates").status_code == 200
        familie = _role_client(ctx, make_token(ctx, "familie"))
        assert familie.post(f"{API_PREFIX}/labels/render", json=body).status_code == 403
        assert familie.get(f"{API_PREFIX}/familie/vorlagen").status_code not in (401, 403)
    finally:
        close_ctx(ctx)


# ---------------------------------------------------------------- Kurz-Link Ende-zu-Ende

def _service_transport(service: TestClient) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        query = request.url.query.decode() if isinstance(request.url.query, bytes) else str(request.url.query)
        url = request.url.path + (f"?{query}" if query else "")
        headers = {k: v for k, v in request.headers.items() if k.lower() in ("authorization", "content-type")}
        answer = service.request(request.method, url, content=request.read(), headers=headers,
                                 follow_redirects=False)
        return httpx.Response(answer.status_code, content=answer.content,
                              headers={"content-type": answer.headers.get("content-type", "application/json")})

    return httpx.MockTransport(handler)


def test_kurzlink_ende_zu_ende(tmp_path):
    service = TestClient(shortlink_service.create_app(tmp_path / "s.db", ADMIN_TOKEN))
    write_homelab({"shortlink": {"base_url": "https://l.example.com", "admin_url": "http://shortlink.test",
                                 "token_ref": token_file(tmp_path, "shortlink", ADMIN_TOKEN)}})
    client, ctx = _make(tmp_path, transports=_all_transports(shortlink=_service_transport(service)))
    try:
        created = client.post(f"{HOMELAB}/assets", json={"bezeichnung": "NAS", "ziel": "https://ziel.example/a"})
        assert created.status_code == 200, created.text
        assert created.json()["assets"][0]["id"] == "HL-0001"

        label = client.get(f"{HOMELAB}/assets/HL-0001/label")
        assert label.status_code == 200, label.text
        assert label.json()["values"]["link"] == "HTTPS://L.EXAMPLE.COM/HL-0001"

        redirect = service.get("/HL-0001", follow_redirects=False)
        assert redirect.status_code == 302
        assert redirect.headers["location"] == "https://ziel.example/a"

        changed = client.put(f"{HOMELAB}/assets/HL-0001", json={"ziel": "https://ziel.example/b"})
        assert changed.status_code == 200, changed.text
        assert changed.json()["warnings"] == []
        redirect = service.get("/HL-0001", follow_redirects=False)
        assert redirect.status_code == 302
        assert redirect.headers["location"] == "https://ziel.example/b"
    finally:
        close_ctx(ctx)


# ---------------------------------------------------------------- Paperless Ende-zu-Ende

PAPERLESS_ROUTES = {
    "GET /api/documents/next_asn/": load_json("paperless/next_asn.json"),
    "GET /api/documents/": load_json("paperless/documents-search.json"),
    "GET /api/documents/17/": load_json("paperless/document-17.json"),
    "GET /api/correspondents/": load_json("paperless/correspondents.json"),
    "GET /api/custom_fields/": load_json("paperless/custom_fields.json"),
}


def test_paperless_asn_serie_ende_zu_ende(tmp_path):
    write_homelab({"paperless": {"token_ref": token_file(tmp_path, "paperless")}})
    client, ctx = _make(tmp_path, transports=_all_transports(paperless=mock_transport(PAPERLESS_ROUTES)))
    try:
        reserved = client.post(f"{HOMELAB}/paperless/asn/reserve", json={"count": 3})
        assert reserved.status_code == 200, reserved.text
        pending_id = reserved.json()["pending_id"]
        plan = client.post(f"{API_PREFIX}/batch/plan",
                           json={"template": "asn", "source": {"type": "pending", "id": pending_id}})
        assert plan.status_code == 200, plan.text
        body = plan.json()
        assert body["count"] == 3
        assert body["errors"] == []
    finally:
        close_ctx(ctx)


# ---------------------------------------------------------------- Scan-Cache aus dem SSH-Scan und Plausi

def test_ssh_scan_fuellt_scan_cache(e2e):
    client, _ctx = e2e
    assert scancache.load_scan("pmx10") is None
    response = client.post(f"{API_PREFIX}/ssh/scan", json={"host": "pmx10"})
    assert response.status_code == 200, response.text
    record = scancache.load_scan("pmx10")
    assert record is not None
    assert {d.device for d in record.disks} == {"sda", "sdb", "nvme0n1"}


def test_ssh_scan_bleibt_erfolgreich_wenn_cache_nicht_schreibbar(e2e, monkeypatch):
    client, _ctx = e2e

    def broken(*args, **kwargs):
        raise OSError("Platte voll")

    monkeypatch.setattr(scancache, "save_scan", broken)
    response = client.post(f"{API_PREFIX}/ssh/scan", json={"host": "pmx10"})
    assert response.status_code == 200, response.text
    assert len(response.json()["disks"]) == 3


def test_cli_disks_scan_fuellt_scan_cache(tmp_path, monkeypatch, capsys):
    config = paths.config_path()
    import json
    data = json.loads(config.read_text(encoding="utf-8")) if config.exists() else {}
    data.update(_ssh_config(tmp_path))
    config.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(disks_cmd, "RUNNER", _ssh_runner)
    assert cli_main(["disks", "scan", "pmx10"]) == 0
    capsys.readouterr()
    record = scancache.load_scan("pmx10")
    assert record is not None
    assert len(record.disks) == 3


def test_cli_disks_scan_cache_fehler_nur_protokolliert(tmp_path, monkeypatch, capsys):
    import json
    config = paths.config_path()
    data = json.loads(config.read_text(encoding="utf-8")) if config.exists() else {}
    data.update(_ssh_config(tmp_path))
    config.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(disks_cmd, "RUNNER", _ssh_runner)

    def broken(*args, **kwargs):
        raise ValueError("kaputt")

    monkeypatch.setattr(scancache, "save_scan", broken)
    assert cli_main(["disks", "scan", "pmx10"]) == 0
    assert "S5Y1NX0R123456" in capsys.readouterr().out


def test_plausi_nutzt_scan_cache_aus_ssh_scan(e2e):
    client, _ctx = e2e
    scanned = client.post(f"{API_PREFIX}/ssh/scan", json={"host": "pmx10"})
    assert scanned.status_code == 200, scanned.text
    response = client.post(f"{HOMELAB}/plausi",
                           json={"template": "datentraeger",
                                 "values": {"host": "pmx20", "sn": "S5Y1NX0R123456"}, "vault": False})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["worst"] == "konflikt"
    assert "sn_anderer_host" in [f["code"] for f in body["findings"]]


# ---------------------------------------------------------------- Fehlerbilder

def test_paperless_ohne_token_datei_ist_424(tmp_path):
    write_homelab({"paperless": {"token_ref": f"file:{tmp_path / 'fehlt' / 'paperless'}"}})
    client, ctx = _make(tmp_path)
    try:
        response = client.get(f"{HOMELAB}/paperless/asn/next")
        assert response.status_code == 424, response.text
        assert response.json()["error"]["message"].startswith("Zugangsdaten: Token fehlt: Paperless")
    finally:
        close_ctx(ctx)


def test_home_assistant_nicht_erreichbar_ist_503(tmp_path):
    write_homelab({"homeassistant": {"token_ref": token_file(tmp_path, "ha")}})
    client, ctx = _make(tmp_path, transports=_all_transports(homeassistant=connect_error_transport()))
    try:
        response = client.get(f"{HOMELAB}/ha/batteries")
        assert response.status_code == 503, response.text
        assert response.json()["error"]["exit_code"] == 5
    finally:
        close_ctx(ctx)


def test_waechter_blockiert_echten_transport():
    with pytest.raises(AssertionError, match="echter HTTP-Transport"):
        with httpx.Client() as client:
            client.get("http://192.0.2.1/")
