"""Ende-zu-Ende-Tests mit dem echten App-Stack (create_app, Middleware, Routen, MCP).

Kein Port, kein Drucker, kein Broker: TestClient mit `client=(ip, port)`, Druckdienst mit
MemoryTransport aus `daemon_fakes`. LAN-Clients kommen aus `192.0.2.0/24`, der Dienst hört
laut `LanPolicy` auf `192.0.2.50:8712`.
"""

from __future__ import annotations

import base64
import json
import os
import threading
import time

import pytest
from fastapi.testclient import TestClient

from daemon_fakes import FakeNow
from tapesmith import config as config_mod
from tapesmith import pipeline
from tapesmith.automation import hotfolder as hotfolder_mod
from tapesmith.daemon.addons import AddonManager
from tapesmith.daemon.instance import SingleInstance, run_daemon
from tapesmith.webapi.access import LanPolicy
from tapesmith.webapi.app import create_app
from webapi_fakes import TOKEN, close_ctx, make_client, make_ctx, make_token

LAN = LanPolicy(enabled=True, networks=("192.0.2.0/24",),
                hosts=frozenset({"192.0.2.50", "p12pc", "p12pc.local"}))
LAN_IP = "192.0.2.77"
LAN_URL = "http://192.0.2.50:8712"
LOCAL_URL = "http://127.0.0.1:8712"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
MCP_PROTOCOL = "2025-06-18"
MCP_TOOLS = {"list_templates", "label_preview", "label_print", "printer_status", "print_history", "queue_list"}


# ---------------------------------------------------------------- Hilfen


@pytest.fixture
def made(tmp_path):
    """Fabrik für (Loopback-Admin-Client, ctx); räumt alle Kontexte am Ende auf."""
    ctxs = []

    def factory(**kw):
        kw.setdefault("lan", LAN)
        kw.setdefault("now", FakeNow())
        client, ctx = make_client(tmp_path, **kw)
        ctxs.append(ctx)
        return client, ctx

    yield factory
    for ctx in ctxs:
        close_ctx(ctx)


def _lan_client(local: TestClient, secret: str | None = None, *, ip: str = LAN_IP) -> TestClient:
    """Zweiter Client an derselben App, diesmal aus dem LAN (optional mit Bearer-Token)."""
    headers = {"Authorization": f"Bearer {secret}"} if secret else {}
    return TestClient(local.app, base_url=LAN_URL, headers=headers, client=(ip, 50124))


def _bearer(secret: str) -> dict:
    return {"Authorization": f"Bearer {secret}"}


def _history(ctx) -> list:
    return ctx.history().search("", 100)


def _create_token(local: TestClient, name: str, role: str) -> dict:
    r = local.post("/api/v1/access/tokens", json={"name": name, "role": role})
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------- 1. Familie vom Handy


def test_family_from_phone(made):
    local, ctx = made()
    created = _create_token(local, "Handy Anna", "familie")
    assert created["token"]["role"] == "familie"
    secret = created["secret"]
    assert secret.startswith("p12_")
    phone = _lan_client(local, secret)

    r = phone.get("/api/v1/familie/vorlagen")
    assert r.status_code == 200, r.text
    names = [t["name"] for t in r.json()["templates"]]
    assert "gefriergut" in names

    r = phone.post("/api/v1/familie/vorschau", json={"template": "gefriergut", "values": {"inhalt": "Gulasch"}})
    assert r.status_code == 200, r.text
    preview = r.json()
    assert preview["ok"] is True
    assert base64.b64decode(preview["design_png"]).startswith(PNG_MAGIC)

    r = phone.post("/api/v1/familie/drucken", json={"template": "gefriergut", "values": {"inhalt": "Gulasch"}})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ok", r.json()
    entries = _history(ctx)
    assert len(entries) == 1 and entries[0].source == "api"

    anonymous = _lan_client(local)
    page = anonymous.get("/familie")
    assert page.status_code == 200
    assert "text/html" in page.headers["content-type"]

    assert phone.get("/api/v1/history").status_code == 403
    assert phone.patch("/api/v1/settings", json={"changes": {}}).status_code == 403
    assert phone.get("/api/v1/access").status_code == 403
    assert phone.post("/api/v1/print/text", json={"text": "A"}).status_code == 403
    assert phone.post("/mcp", json={}).status_code == 403


# ---------------------------------------------------------------- 2. Widerruf


def test_revoke_locks_token(made):
    local, _ctx = made()
    created = _create_token(local, "Handy Ben", "familie")
    phone = _lan_client(local, created["secret"])
    assert phone.get("/api/v1/familie/vorlagen").status_code == 200

    r = local.delete(f"/api/v1/access/tokens/{created['token']['id']}")
    assert r.status_code == 200, r.text
    r = phone.get("/api/v1/familie/vorlagen")
    assert r.status_code == 401
    assert r.json()["error"]["message"] == "Nicht angemeldet: Token fehlt oder ist falsch"
    assert all(t["id"] != created["token"]["id"] for t in local.get("/api/v1/access").json()["tokens"])


# ---------------------------------------------------------------- 3. Rate-Limit


def test_rate_limit_after_ten_failures(made):
    local, ctx = made()
    good = make_token(ctx, "familie")
    attacker = _lan_client(local, "p12_deadbeef_" + "x" * 30)
    for _ in range(10):
        assert attacker.get("/api/v1/familie/vorlagen").status_code == 401
    r = attacker.get("/api/v1/familie/vorlagen")
    assert r.status_code == 429
    assert 0 < int(r.headers["retry-after"]) <= 900
    assert r.json()["error"]["message"] == "Zu viele Fehlversuche, bitte später erneut versuchen"
    # gesperrt ist die Adresse, auch mit richtigem Token und für /health
    assert attacker.get("/api/v1/familie/vorlagen", headers=_bearer(good)).status_code == 429
    assert attacker.get("/health").status_code == 429
    # andere LAN-Adresse und Loopback bleiben unberührt
    assert _lan_client(local, good, ip="192.0.2.78").get("/api/v1/familie/vorlagen").status_code == 200
    assert local.get("/api/v1/app").status_code == 200
    for _ in range(12):
        assert local.get("/api/v1/app", headers={"X-P12-Token": "falsch"}).status_code == 401
    assert local.get("/api/v1/app").status_code == 200


# ---------------------------------------------------------------- 4. Fremdes Netz, Rebinding


def test_foreign_network_and_rebinding(made):
    local, ctx = made()
    admin = make_token(ctx, "admin")
    foreign = _lan_client(local, admin, ip="10.9.9.9")
    for path in ("/health", "/familie", "/api/v1/app"):
        r = foreign.get(path)
        assert r.status_code == 403, path
        assert r.json()["error"]["message"] == "Zugriff verweigert: Adresse nicht freigegeben"

    lan = _lan_client(local, admin)
    assert lan.get("/api/v1/app").status_code == 200
    evil = lan.get("/api/v1/app", headers={"Host": "evil.example:8712"})
    assert evil.status_code == 403
    assert lan.get("/health", headers={"Host": "evil.example:8712"}).status_code == 403
    assert lan.get("/api/v1/app", headers={"Host": "p12pc.local:8712"}).status_code == 200
    assert lan.get("/api/v1/app", headers={"Origin": "http://evil.example"}).status_code == 403

    health = lan.get("/health").json()
    assert set(health) == {"ok", "app", "version"}
    assert "home_key" in local.get("/health").json()


# ---------------------------------------------------------------- 5. Standard ohne LAN


def test_default_without_lan(made):
    local, ctx = made(lan=LanPolicy.disabled())
    admin = make_token(ctx, "admin")
    lan = _lan_client(local, admin)
    for method, path in (("GET", "/health"), ("GET", "/familie"), ("GET", "/api/v1/app"),
                         ("GET", "/api/v1/familie/vorlagen"), ("POST", "/api/v1/print/text"), ("POST", "/mcp")):
        r = lan.request(method, path, json={} if method == "POST" else None)
        assert r.status_code == 403, (method, path)
    assert local.get("/health").status_code == 200
    assert local.get("/api/v1/app").status_code == 200
    assert local.get("/api/v1/app", headers=_bearer(admin)).status_code == 200


# ---------------------------------------------------------------- 6. Kurzendpunkte


def test_short_endpoints_with_print_token(made):
    local, ctx = made()
    secret = make_token(ctx, "drucken")
    lan = _lan_client(local, secret)

    r = lan.post("/api/v1/print", json={"template": "gefriergut", "values": {"inhalt": "Linsen"}})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ok"
    assert ctx.history().get(r.json()["history_id"]).source == "api"

    anonymous = _lan_client(local)
    png = anonymous.get("/api/v1/preview.png", params={"text": "A", "t": secret})
    assert png.status_code == 200, png.text
    assert png.headers["content-type"] == "image/png"
    assert png.content.startswith(PNG_MAGIC)

    jobs = lan.get("/api/v1/jobs")
    assert jobs.status_code == 200
    assert "jobs" in jobs.json()

    docs = anonymous.get("/api/v1/docs", params={"t": secret})
    assert docs.status_code == 200
    assert docs.headers["content-type"].startswith("text/html")
    assert "<script" not in docs.text.lower()
    assert "/api/v1/print" in docs.text

    # ohne Token nichts, Token per Query nur bei GET
    assert anonymous.get("/api/v1/jobs").status_code == 401
    r = _lan_client(local).post(f"/api/v1/print/text?t={secret}", json={"text": "A"})
    assert r.status_code == 401
    # Verwaltung bleibt gesperrt
    assert lan.get("/api/v1/access").status_code == 403
    assert lan.patch("/api/v1/settings", json={"changes": {}}).status_code == 403


# ---------------------------------------------------------------- 7. MCP über HTTP


def _rpc(client: TestClient, method: str, params: dict | None = None, *, id: int = 1,
         headers: dict | None = None):
    body = {"jsonrpc": "2.0", "id": id, "method": method}
    if params is not None:
        body["params"] = params
    hdrs = dict(MCP_HEADERS)
    if method != "initialize":
        hdrs["MCP-Protocol-Version"] = MCP_PROTOCOL
    hdrs.update(headers or {})
    return client.post("/mcp", json=body, headers=hdrs, follow_redirects=False)


def _initialize(client: TestClient, **kw):
    return _rpc(client, "initialize", {"protocolVersion": MCP_PROTOCOL, "capabilities": {},
                                       "clientInfo": {"name": "e2e", "version": "1"}}, **kw)


def _tool(client: TestClient, name: str, arguments: dict, *, id: int) -> dict:
    r = _rpc(client, "tools/call", {"name": name, "arguments": arguments}, id=id)
    assert r.status_code == 200, r.text
    return r.json()["result"]


def _tool_json(result: dict) -> dict:
    return json.loads(next(c for c in result["content"] if c["type"] == "text")["text"])


def test_mcp_over_http(made):
    local, ctx = made()
    ctx.service._debouncer._min_interval_s = 0
    secret = make_token(ctx, "drucken")
    with _lan_client(local) as anonymous:
        assert _initialize(anonymous).status_code == 401
        family = make_token(ctx, "familie")
        assert _initialize(anonymous, headers=_bearer(family)).status_code == 403
    with _lan_client(local, secret) as lan:
        r = _initialize(lan)
        assert r.status_code == 200, r.text
        tools = _rpc(lan, "tools/list", id=2)
        assert tools.status_code == 200
        assert {t["name"] for t in tools.json()["result"]["tools"]} == MCP_TOOLS

        preview = _tool_json(_tool(lan, "label_preview", {"text": ["MCP Ende zu Ende"]}, id=3))
        assert preview["ok"] is True and preview["preview_id"]
        no = _tool_json(_tool(lan, "label_print", {"preview_id": preview["preview_id"]}, id=4))
        assert no["printed"] is False
        assert _history(ctx) == []

        yes = _tool_json(_tool(lan, "label_print", {"preview_id": preview["preview_id"], "confirm": True}, id=5))
        assert yes["printed"] is True, yes
        entries = _history(ctx)
        assert len(entries) == 1 and entries[0].source == "mcp"


# ---------------------------------------------------------------- 8. Addons im Dienst


class _FakePipeServer:
    def __init__(self, service, **kw):
        self.clients = 0

    def start(self):
        pass

    def stop(self):
        pass


class _FakeWeb:
    def __init__(self, ctx):
        self.ctx = ctx
        self.clients = 0
        self.started = self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


class _FakeTelegram:
    name = "telegram"

    def __init__(self):
        self.running = False

    def start(self):
        self.running = True

    def stop(self):
        self.running = False

    def status(self):
        return {"name": self.name, "running": self.running, "error": None, "detail": "Test-Bot"}


class _NoCloseService:
    """Reicht den echten Dienst durch, schließt ihn aber nicht (das macht `close_ctx`)."""

    def __init__(self, service):
        self._service = service

    def __getattr__(self, name):
        return getattr(self._service, name)

    def close(self):
        pass


def _wait_for(predicate, timeout_s: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def test_addons_in_daemon(tmp_path):
    inbox = tmp_path / "hotfolder"
    config = {"hotfolder": {"enabled": True, "dir": str(inbox), "poll_s": 60.0, "settle_s": 0}}
    ctx = make_ctx(tmp_path, config=config, lan=LAN, now=FakeNow())
    inbox.mkdir()
    (inbox / "gulasch.json").write_text(
        json.dumps({"template": "gefriergut", "values": {"inhalt": "Gulasch"}}), encoding="utf-8")
    from tapesmith.automation.facade import LabelFacade

    facade = LabelFacade.from_ctx(ctx)
    telegram = _FakeTelegram()
    factories = {
        "hotfolder": hotfolder_mod.create,
        "mqtt": lambda _facade, _cfg: None,
        "telegram": lambda _facade, _cfg: telegram,
    }
    managers: list[AddonManager] = []

    def addons_factory(_service):
        manager = AddonManager(facade, factories)
        managers.append(manager)
        return manager

    web = _FakeWeb(ctx)
    stop = threading.Event()
    result: dict = {}
    mutex = f"Local\\Tapesmith.Test.W4E2E.{os.getpid()}.{id(stop)}"

    def run():
        result["rc"] = run_daemon(service_factory=lambda: _NoCloseService(ctx.service),
                                  server_factory=_FakePipeServer, runner_factory=lambda s: None,
                                  instance=SingleInstance(mutex), stop_event=stop, idle_exit_s=0,
                                  tick_s=0.01, web_factory=lambda s: web, addons_factory=addons_factory)

    thread = threading.Thread(target=run, name="e2e-lan-daemon", daemon=True)
    thread.start()
    try:
        assert _wait_for(lambda: "addons" in ctx.extras)
        assert ctx.extras["addons"] is managers[0]
        assert _wait_for(lambda: (inbox / "done" / "gulasch.json").exists())
        entries = _history(ctx)
        assert len(entries) == 1 and entries[0].source == "hotfolder"

        with TestClient(create_app(ctx), base_url=LOCAL_URL, headers={"X-P12-Token": TOKEN},
                        client=("127.0.0.1", 50123)) as local:
            data = local.get("/api/v1/access").json()
        statuses = {s["name"]: s for s in data["addons"]}
        assert set(statuses) == {"hotfolder", "mqtt", "telegram"}
        assert statuses["hotfolder"]["running"] is True
        assert "1 verarbeitet" in statuses["hotfolder"]["detail"]
        assert statuses["telegram"] == {"name": "telegram", "running": True, "error": None, "detail": "Test-Bot"}
        assert statuses["mqtt"]["running"] is False and statuses["mqtt"]["detail"] == "aus"
    finally:
        stop.set()
        thread.join(timeout=10)
        close_ctx(ctx)
    assert result.get("rc") == 0
    assert web.started and web.stopped
    assert telegram.running is False


# ---------------------------------------------------------------- 9. Kontingent


def test_quota_for_api_source(made):
    # Job-Kontingent wie im Standard (20 je Stunde), Millimeter hoch gesetzt, damit genau das
    # Job-Kontingent greift: bei etwa 55 mm je Textlabel wäre sonst nach 18 Drucken das
    # mm-Kontingent (1000 mm je Stunde) erschöpft.
    quotas = {"api": {"jobs_per_hour": 20, "mm_per_hour": 100000}}
    local, ctx = made(config={"guard": {"quotas": quotas}})
    lan = _lan_client(local, make_token(ctx, "drucken"))
    statuses = []
    for i in range(1, 22):
        r = lan.post("/api/v1/print/text", json={"text": f"Nr {i}"})
        assert r.status_code == 200, r.text
        statuses.append(r.json())
    assert [s["status"] for s in statuses[:20]] == ["ok"] * 20, [s["reasons"] for s in statuses]
    last = statuses[20]
    assert last["status"] == "abgelehnt"
    assert any("Kontingent für api erschöpft: 20 Jobs pro Stunde" in reason for reason in last["reasons"]), last
    assert pipeline.DOUBLE_PRESS_REASON not in last["reasons"]
    assert {e.source for e in _history(ctx)} == {"api"}
    # die Sitzung (Quelle gui) hat kein Kontingent
    r = local.post("/api/v1/print/text", json={"text": "Nr 22"})
    assert r.json()["status"] == "ok"


def test_default_mm_quota_for_api_source(made):
    """Standard-Kontingent `api` (1000 mm je Stunde) greift ebenfalls, mit eigener Meldung."""
    local, ctx = made()
    lan = _lan_client(local, make_token(ctx, "drucken"))
    for i in range(1, 30):
        body = lan.post("/api/v1/print/text", json={"text": f"Nr {i}"}).json()
        if body["status"] != "ok":
            break
    assert body["status"] == "abgelehnt"
    assert any("Kontingent für api erschöpft: 1000 mm pro Stunde" in reason for reason in body["reasons"]), body
    assert pipeline.DOUBLE_PRESS_REASON not in body["reasons"]


# ---------------------------------------------------------------- 10. Kopiengrenze je Quelle


def test_copy_limits_per_source(made):
    local, ctx = made()
    ctx.service._debouncer._min_interval_s = 0
    lan = _lan_client(local, make_token(ctx, "drucken"))
    gulasch = {"template": "gefriergut", "values": {"inhalt": "Gulasch"}, "copies": 6}

    for confirmed in (False, True):
        r = lan.post("/api/v1/print", json={**gulasch, "confirmed": confirmed})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "abgelehnt"
        assert any("kann nicht bestätigen" in reason for reason in body["reasons"]), body["reasons"]
    assert _history(ctx) == []

    r = local.post("/api/v1/print", json=gulasch)
    assert r.json()["status"] == "bestätigung_nötig"
    r = local.post("/api/v1/print", json={**gulasch, "confirmed": True})
    assert r.json()["status"] == "ok", r.json()
    assert ctx.history().get(r.json()["history_id"]).source == "gui"

    phone = _lan_client(local, make_token(ctx, "familie"))
    assert phone.get("/api/v1/familie/vorlagen").json()["max_copies"] == 5
    r = phone.post("/api/v1/familie/drucken",
                   json={"template": "gefriergut", "values": {"inhalt": "Gulasch"}, "copies": 6})
    assert r.status_code == 422

    with lan:
        assert _initialize(lan).status_code == 200
        result = _tool(lan, "label_preview", {"text": ["A"], "copies": 6}, id=2)
        assert result["isError"] is True
        assert "1 bis 5" in result["content"][0]["text"]


def test_family_max_copies_capped_by_guard(made):
    local, ctx = made()
    config_mod.set_setting("family.max_copies", 10)
    phone = _lan_client(local, make_token(ctx, "familie"))
    assert phone.get("/api/v1/familie/vorlagen").json()["max_copies"] == 5


# ---------------------------------------------------------------- Eingecheckter Web-Build


def test_checked_in_build_serves_family_and_access(made):
    from tapesmith import webui

    static = webui.static_dir()
    assets = static / "assets"
    assert (static / "index.html").is_file()
    assert list(assets.glob("FamilyApp-*.js")), "Chunk der Familienseite fehlt im Build"
    access_chunks = [p for p in assets.glob("*.js") if "Tokens" in p.read_text(encoding="utf-8")
                     and "Zugriff" in p.read_text(encoding="utf-8")]
    assert access_chunks, "Chunk der Seite Zugriff fehlt im Build"

    local, _ctx = made(static_dir=static)
    phone = _lan_client(local)
    for path in ("/familie", "/zugriff"):
        r = phone.get(path)
        assert r.status_code == 200, path
        assert "/assets/" in r.text or "assets/" in r.text


_DOCS = ("README.md", "docs/handbuch.md", "docs/hardware/README.md", "web/README.md")


@pytest.mark.parametrize("rel", _DOCS)
def test_docs_have_no_control_characters(rel):
    """Doku darf keine Steuerzeichen enthalten (z. B. BEL/TAB aus kaputten `\a`/`\t`-Ersetzungen)."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, rel), encoding="utf-8") as fh:
        text = fh.read()
    bad = sorted({hex(ord(c)) for c in text if ord(c) < 32 and c not in "\n\r"})
    assert not bad, f"{rel}: Steuerzeichen {bad}"


def test_handbook_documents_token_file_path():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "docs/handbuch.md"), encoding="utf-8") as fh:
        text = fh.read()
    assert r"`%APPDATA%\Tapesmith\access\tokens.json`" in text
