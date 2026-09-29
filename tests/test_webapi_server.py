"""Web-Server-Einstellungen, Start/Stopp (ohne echten Port, ohne echtes uvicorn), Sitzung."""

import json
import os
from datetime import datetime

import pytest

from daemon_fakes import close_service, make_service
from tapesmith.webapi import session
from tapesmith.webapi.server import DEFAULT_PORT, WebServer, default_web, web_settings


def test_web_settings_defaults_and_env():
    assert web_settings({}, env={}) == 8712
    assert DEFAULT_PORT == 8712
    assert web_settings({}, env={"TAPESMITH_WEB_PORT": "0"}) == 0
    assert web_settings({"web": {"port": 9000}}, env={"TAPESMITH_WEB_PORT": "9100"}) == 9100
    with pytest.raises(ValueError):
        web_settings({}, env={"TAPESMITH_WEB_PORT": "abc"})
    with pytest.raises(ValueError):
        web_settings({}, env={"TAPESMITH_WEB_PORT": "70000"})
    # alter Schlüssel web.enabled wird ignoriert: die Web-Oberfläche läuft immer
    assert web_settings({"web": {"enabled": False}}, env={}) == 8712
    assert web_settings({"web": {"port": 9000}}, env={}) == 9000
    with pytest.raises(ValueError):
        web_settings({"web": {"port": 70000}}, env={})
    assert web_settings({"web": None}, env={}) == 8712


class FakeSocket:
    def __init__(self, port=54321):
        self.port = port
        self.closed = False

    def getsockname(self):
        return ("127.0.0.1", self.port)

    def close(self):
        self.closed = True


class FakeUvicorn:
    def __init__(self, cfg, started=True):
        self.config = cfg
        self.started = started
        self.should_exit = False
        self.ran_with = None

    def run(self, sockets=None):
        self.ran_with = sockets

    def install_signal_handlers(self):
        raise AssertionError("darf nicht aufgerufen werden")


@pytest.fixture
def service(tmp_path):
    svc, _ = make_service(tmp_path)
    added = []
    real = svc.add_emitter

    def spy(fn):
        added.append(fn)
        real(fn)

    svc.add_emitter = spy
    svc._added = added
    yield svc
    close_service(svc)


def test_start_writes_session_and_stop_removes(service, tmp_path):
    sock = FakeSocket()
    servers = []

    def factory(cfg):
        server = FakeUvicorn(cfg)
        servers.append(server)
        return server

    web = WebServer(service, port=0, home_key="hk", static_dir=tmp_path, token="tok",
                    server_factory=factory, socket_factory=lambda port: sock,
                    now=lambda: datetime(2026, 9, 28, 12, 0, 0))
    web.start()
    try:
        data = json.loads(session.session_path().read_text(encoding="utf-8"))
        assert data == {"port": 54321, "token": "tok", "pid": os.getpid(), "home_key": "hk",
                        "started": "2026-09-28T12:00:00"}
        assert web.port == 54321 and web.token == "tok"
        assert web.ctx is not None and web.ctx.port == 54321
        assert service._added and service._added[0] == web.ctx.broker.publish
        cfg = servers[0].config
        assert cfg.log_config is None and cfg.access_log is False and cfg.lifespan == "on"
        web._thread.join(2)
        assert servers[0].ran_with == [sock]
    finally:
        ctx = web.ctx
        web.stop()
    assert not session.session_path().exists()
    assert servers[0].should_exit is True
    assert sock.closed
    assert ctx.closed


def test_clients_counts_open_event_streams(service, tmp_path):
    web = WebServer(service, port=0, home_key="hk", static_dir=tmp_path, token="tok",
                    server_factory=FakeUvicorn, socket_factory=lambda port: FakeSocket())
    assert web.clients == 0                # vor dem Start
    web.start()
    try:
        sub = web.ctx.broker.subscribe()
        other = web.ctx.broker.subscribe()
        assert web.clients == 2
        sub.close()
        assert web.clients == 1
        other.close()
        assert web.clients == 0
    finally:
        web.stop()
    assert web.clients == 0                # nach dem Stopp


def test_default_token_bleibt_ueber_neustarts_gleich(service, tmp_path):
    # Offene Browser-Tabs müssen einen Neustart des Dienstes (Update, Leerlauf-Ende, PC-Neustart)
    # überstehen: das Token wird einmal zufällig erzeugt und danach wiederverwendet.
    web = WebServer(service, port=0, home_key="hk", static_dir=tmp_path,
                    server_factory=FakeUvicorn, socket_factory=lambda port: FakeSocket())
    other = WebServer(service, port=0, home_key="hk", static_dir=tmp_path,
                      server_factory=FakeUvicorn, socket_factory=lambda port: FakeSocket())
    assert len(web.token) >= 32 and web.token == other.token


def test_token_zuruecksetzen_erzeugt_neues(service, tmp_path):
    first = session.load_or_create_token()
    assert session.load_or_create_token() == first
    renewed = session.reset_token()
    assert renewed != first and len(renewed) >= 32
    assert session.load_or_create_token() == renewed


def test_kaputte_tokendatei_wird_ersetzt(service, tmp_path):
    session.token_path().parent.mkdir(parents=True, exist_ok=True)
    session.token_path().write_text("zu kurz", encoding="utf-8")
    token = session.load_or_create_token()
    assert len(token) >= 32 and token != "zu kurz"


def test_socket_error_propagates(service, tmp_path):
    def fail(port):
        raise OSError("belegt")

    web = WebServer(service, port=8712, home_key="hk", static_dir=tmp_path, server_factory=FakeUvicorn,
                    socket_factory=fail)
    with pytest.raises(OSError):
        web.start()
    assert not session.session_path().exists()
    web.stop()      # harmlos


def test_server_never_started(service, tmp_path):
    sock = FakeSocket()
    web = WebServer(service, port=0, home_key="hk", static_dir=tmp_path,
                    server_factory=lambda cfg: FakeUvicorn(cfg, started=False),
                    socket_factory=lambda port: sock, start_timeout_s=0.1)
    with pytest.raises(RuntimeError):
        web.start()
    assert not session.session_path().exists()
    assert sock.closed


def test_session_roundtrip():
    assert session.read_session() is None
    session.write_session(port=1, token="t", pid=42, home_key="h", started=datetime(2026, 1, 2, 3, 4, 5))
    assert session.read_session()["port"] == 1
    session.remove_session(41)
    assert session.session_path().exists()
    session.remove_session(42)
    assert not session.session_path().exists()
    session.session_path().parent.mkdir(parents=True, exist_ok=True)
    session.session_path().write_text("{kaputt", encoding="utf-8")
    assert session.read_session() is None


def test_default_web(monkeypatch):
    class Svc:
        config = {"web": {"enabled": False}}

    # web.enabled = false aus einer alten config.json wird ignoriert: der Server entsteht trotzdem
    monkeypatch.delenv("TAPESMITH_WEB_PORT", raising=False)
    web = default_web(Svc())
    assert isinstance(web, WebServer) and web.port == 8712
    Svc.config = {}
    monkeypatch.setenv("TAPESMITH_WEB_PORT", "0")
    web = default_web(Svc())
    assert isinstance(web, WebServer) and web.port == 0
