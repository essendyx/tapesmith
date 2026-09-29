"""LAN-Bindung des Web-Servers (Fake-Sockets, Fake-uvicorn, kein echter Port) und Lifespan."""

import contextlib

import pytest
from fastapi.testclient import TestClient

from daemon_fakes import close_service, make_service
from tapesmith.webapi.access import LanPolicy
from tapesmith.webapi.app import create_app
from tapesmith.webapi.server import WebServer, default_web
from webapi_fakes import close_ctx, make_ctx

LAN = LanPolicy(enabled=True, networks=("192.0.2.0/24",), hosts=frozenset({"192.0.2.50"}))


class FakeSocket:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.closed = False

    def getsockname(self):
        return (self.host, self.port)

    def close(self):
        self.closed = True


class Factory:
    """Merkt sich jeden Bind-Aufruf; Port 0 ergibt 54321; `fail` = Hosts, die OSError werfen."""

    def __init__(self, fail=()):
        self.calls = []
        self.sockets = []
        self.fail = set(fail)

    def __call__(self, port, host="127.0.0.1"):
        self.calls.append((host, port))
        if host in self.fail:
            raise OSError(f"{host} nicht verfügbar")
        sock = FakeSocket(host, port or 54321)
        self.sockets.append(sock)
        return sock


class FakeUvicorn:
    instances = []

    def __init__(self, cfg):
        self.config = cfg
        self.started = True
        self.should_exit = False
        self.ran_with = None
        FakeUvicorn.instances.append(self)

    def run(self, sockets=None):
        self.ran_with = sockets


@pytest.fixture
def service(tmp_path):
    svc, _ = make_service(tmp_path)
    FakeUvicorn.instances = []
    yield svc
    close_service(svc)


def _start(service, tmp_path, factory, *, port=0, lan=None, lan_bind=None):
    web = WebServer(service, port=port, home_key="hk", static_dir=tmp_path, token="tok",
                    server_factory=FakeUvicorn, socket_factory=factory, lan=lan, lan_bind=lan_bind)
    web.start()
    web._thread.join(2)
    return web


def test_lan_off_single_loopback_socket(service, tmp_path):
    factory = Factory()
    web = _start(service, tmp_path, factory, port=8712)
    try:
        assert factory.calls == [("127.0.0.1", 8712)]
        assert web.ctx.extras["listen"] == ["127.0.0.1:8712"]
        assert "lan_error" not in web.ctx.extras
        assert web.ctx.lan.enabled is False
        assert FakeUvicorn.instances[0].ran_with == factory.sockets
        assert FakeUvicorn.instances[0].config.lifespan == "on"
    finally:
        web.stop()
    assert all(s.closed for s in factory.sockets)


def test_lan_all_interfaces_single_socket(service, tmp_path):
    factory = Factory()
    web = _start(service, tmp_path, factory, port=0, lan=LAN, lan_bind="0.0.0.0")
    try:
        assert factory.calls == [("0.0.0.0", 0)]
        assert web.ctx.extras["listen"] == ["0.0.0.0:54321"]
        assert web.port == 54321
        assert web.ctx.lan is LAN
    finally:
        web.stop()


def test_lan_specific_address_two_sockets(service, tmp_path):
    factory = Factory()
    web = _start(service, tmp_path, factory, port=0, lan=LAN, lan_bind="192.0.2.50")
    try:
        assert factory.calls == [("127.0.0.1", 0), ("192.0.2.50", 54321)]
        assert web.ctx.extras["listen"] == ["127.0.0.1:54321", "192.0.2.50:54321"]
        assert FakeUvicorn.instances[0].ran_with == factory.sockets
        assert len(factory.sockets) == 2
    finally:
        web.stop()
    assert all(s.closed for s in factory.sockets)


def test_lan_socket_error_runs_local(service, tmp_path, caplog):
    factory = Factory(fail={"192.0.2.50"})
    web = _start(service, tmp_path, factory, port=8712, lan=LAN, lan_bind="192.0.2.50")
    try:
        assert web.ctx.extras["listen"] == ["127.0.0.1:8712"]
        assert "nicht verfügbar" in web.ctx.extras["lan_error"]
        assert FakeUvicorn.instances[0].ran_with == factory.sockets
        assert "LAN" in caplog.text
    finally:
        web.stop()


def test_lan_all_interfaces_error_falls_back(service, tmp_path):
    factory = Factory(fail={"0.0.0.0"})
    web = _start(service, tmp_path, factory, port=8712, lan=LAN, lan_bind="0.0.0.0")
    try:
        assert factory.calls == [("0.0.0.0", 8712), ("127.0.0.1", 8712)]
        assert web.ctx.extras["listen"] == ["127.0.0.1:8712"]
        assert web.ctx.extras["lan_error"]
    finally:
        web.stop()


def test_lan_config_snapshot(service, tmp_path):
    web = _start(service, tmp_path, Factory(), port=8712)
    try:
        snapshot = web.ctx.extras["lan_config"]
        assert snapshot["enabled"] is False and snapshot["bind"] == "0.0.0.0"
        assert snapshot["allowed_networks"] == ["192.168.0.0/16"]
        assert set(snapshot) == {"enabled", "bind", "allowed_networks", "hostnames", "public_url"}
    finally:
        web.stop()


def test_default_web_passes_lan(monkeypatch):
    class Svc:
        config = {"lan": {"enabled": True, "bind": "192.0.2.50"}}

    monkeypatch.delenv("TAPESMITH_WEB_PORT", raising=False)
    web = default_web(Svc())
    assert web.lan.enabled is True and "192.0.2.50" in web.lan.hosts
    assert web.lan_bind == "192.0.2.50"
    Svc.config = {}
    web = default_web(Svc())
    assert web.lan.enabled is False and web.lan_bind == "0.0.0.0"


def test_lifespan_entries_entered_and_left(tmp_path):
    ctx = make_ctx(tmp_path)
    events = []

    @contextlib.asynccontextmanager
    async def first():
        events.append("rein 1")
        yield
        events.append("raus 1")

    @contextlib.asynccontextmanager
    async def second():
        events.append("rein 2")
        yield
        events.append("raus 2")

    try:
        app = create_app(ctx)
        # MCP (/mcp) hängt seinen Sitzungsmanager als ersten Eintrag an
        assert len(app.state.lifespans) == 1
        app.state.lifespans.extend([first, second])
        with TestClient(app, client=("127.0.0.1", 1)):
            assert events == ["rein 1", "rein 2"]
        assert events == ["rein 1", "rein 2", "raus 2", "raus 1"]
    finally:
        close_ctx(ctx)
