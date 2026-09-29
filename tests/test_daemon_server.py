"""Pipe-Server des Druckdienstes (Protokoll v1): Dispatch, echte lokale Pipe, Ereignisse, Fehler."""

import threading
import time

import pytest

from daemon_fakes import INIT_PACKET, STATUS_OK, close_service, make_service, request, wait_until
from tapesmith.daemon.server import DaemonServer
from tapesmith.ipc import protocol
from tapesmith.ipc.codec import encode_request
from tapesmith.ipc.pipe import client_handshake, connect, memory_channel_pair
from tapesmith.transport.base import MemoryTransport


@pytest.fixture
def svc(tmp_path):
    made = []

    def build(**kw):
        service, transport = make_service(tmp_path / f"s{len(made)}", **kw)
        made.append(service)
        return service, transport

    for i in range(3):
        (tmp_path / f"s{i}").mkdir()
    yield build
    for service in made:
        close_service(service)


@pytest.fixture
def servers():
    made = []
    channels = []

    def start(service, **kw):
        server = DaemonServer(service, **kw)
        server.start()
        made.append(server)
        return server

    def client(server):
        ch = connect(server.name)
        channels.append(ch)
        client_handshake(ch, "test")
        return ch

    yield start, client
    for ch in channels:
        ch.close()
    for server in made:
        server.stop()


def req(msg_id, method, params=None):
    return protocol.request(msg_id, method, params or {})


def read_until_response(ch, msg_id, timeout=5.0):
    events = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        msg = ch.recv(timeout=0.2)
        if msg is None:
            continue
        if msg["type"] == "response" and msg["id"] == msg_id:
            return msg, events
        if msg["type"] == "event":
            events.append(msg)
    raise AssertionError(f"keine Antwort auf {msg_id}")


def print_params(key, mark=1, **kw):
    return {"job_key": key, "request": encode_request(request(mark, **kw)), "enqueue_on_offline": False}


class Blocking(MemoryTransport):
    def __init__(self, responses):
        super().__init__(responses)
        self.gate = threading.Event()
        self.entered = threading.Event()

    def write(self, data):
        if data == INIT_PACKET and not self.gate.is_set():
            self.entered.set()
            self.gate.wait(5)
        super().write(data)


# 19
def test_dispatch_schemas(svc):
    service, _t = svc()
    server = DaemonServer(service)
    a, _b = memory_channel_pair()
    ping = server.dispatch(a, req(1, "ping"))
    assert ping["ok"] is True and ping["id"] == 1
    assert set(ping["result"]) == {"pid", "uptime_s", "clients", "version"}
    state = server.dispatch(a, req(2, "state"))["result"]
    assert set(state) == {"state", "transport", "last_error", "leased"}
    assert state["state"] == "getrennt" and state["leased"] is False
    snap = server.dispatch(a, req(3, "queue.list", {"include_done": True}))["result"]
    assert set(snap) == {"jobs", "paused", "auto_retry", "next_try", "probe", "waiting_reason"}
    assert snap["jobs"] == []
    status = server.dispatch(a, req(4, "status", {"quick": True, "fresh": False}))["result"]
    assert set(status) == {"state", "status", "checked_at"} and status["status"] is None
    assert server.dispatch(a, req(5, "reload"))["result"] == {"profile": "P12"}
    assert server.dispatch(a, req(6, "continue_cut"))["result"] == {"was_pausing": False}
    assert server.dispatch(a, req(7, "cancel", {"job_key": "x"}))["result"] == {"cancelled": False}
    assert server.dispatch(a, req(8, "queue.pause"))["result"] == {}
    assert server.dispatch(a, req(9, "queue.resume"))["result"] == {}
    assert server.dispatch(a, req(10, "queue.retry", {"id": None}))["result"] == {}
    bad = server.dispatch(a, req(11, "queue.cancel", {}))
    assert bad["ok"] is False and bad["error"]["kind"] == "ProtocolError"


# 20
def test_print_over_real_pipe(svc, servers):
    start, client = servers
    service, transport = svc()
    server = start(service)
    ch = client(server)
    assert wait_until(lambda: server.clients == 1)
    ch.send(req(1, "print", print_params("k1", rows=600)))
    response, events = read_until_response(ch, 1)
    assert response["ok"] is True
    assert response["result"]["status"] == "ok"
    assert response["result"]["history_id"] is not None
    names = {e["event"] for e in events}
    assert {"job", "progress"} <= names
    phases = [e["data"]["phase"] for e in events if e["event"] == "job"]
    assert phases[:2] == ["angenommen", "läuft"]


# 21
def test_cancel_while_printing(svc, servers):
    start, client = servers
    transport = Blocking(STATUS_OK)
    service, _t = svc(transport=transport)
    server = start(service)
    ch = client(server)
    ch.send(req(1, "print", print_params("k1")))
    assert transport.entered.wait(5)
    ch.send(req(2, "cancel", {"job_key": "k1"}))
    cancel, _ = read_until_response(ch, 2)
    assert cancel["result"] == {"cancelled": True}
    transport.gate.set()
    response, _ = read_until_response(ch, 1)
    assert response["result"]["status"] == "abgebrochen"


# 22
def test_events_reach_all_clients(svc, servers):
    start, client = servers
    service, _t = svc()
    server = start(service)
    a = client(server)
    b = client(server)
    assert wait_until(lambda: server.clients == 2)
    a.send(req(1, "print", print_params("from-a")))
    read_until_response(a, 1)
    seen = []
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        msg = b.recv(timeout=0.2)
        if msg is None:
            continue
        if msg["type"] == "event" and msg["event"] == "job":
            seen.append(msg["data"])
            if msg["data"]["phase"] == "fertig":
                break
    assert [d["phase"] for d in seen] == ["angenommen", "läuft", "fertig"]
    assert all(d["job_key"] == "from-a" for d in seen)


# 23
def test_errors_and_lease_release_on_close(svc, servers):
    start, client = servers
    service, _t = svc()
    server = start(service)
    a, _b = memory_channel_pair()
    service.lease("andere")
    busy = server.dispatch(a, req(1, "print", print_params("x")))
    assert busy["ok"] is False
    assert busy["error"]["kind"] == "PrinterBusy"
    assert busy["error"]["exit_code"] == 7
    service.release_owner("andere")

    unknown = server.dispatch(a, {"type": "request", "id": 2, "method": "gibtsnicht", "params": {}})
    assert unknown["ok"] is False and unknown["error"]["kind"] == "ProtocolError"

    ch = client(server)
    ch.send(req(3, "lease", {"timeout_s": 60}))
    lease, _ = read_until_response(ch, 3)
    assert lease["ok"] is True and lease["result"]["lease_id"]
    assert service.leased
    ch.close()
    assert wait_until(lambda: not service.leased)


# 24
def test_shutdown(svc):
    service, _t = svc()
    calls = []
    server = DaemonServer(service, on_shutdown=lambda: calls.append(1))
    a, _b = memory_channel_pair()
    service._job_lock.acquire()
    try:
        assert server.dispatch(a, req(1, "shutdown", {"force": False}))["result"] == {"stopping": False}
        assert calls == []
    finally:
        service._job_lock.release()
    assert server.dispatch(a, req(2, "shutdown", {"force": False}))["result"] == {"stopping": True}
    assert calls == [1]


def test_forced_shutdown_while_busy(svc):
    service, _t = svc()
    calls = []
    server = DaemonServer(service, on_shutdown=lambda: calls.append(1))
    a, _b = memory_channel_pair()
    service._job_lock.acquire()
    try:
        assert server.dispatch(a, req(1, "shutdown", {"force": True}))["result"] == {"stopping": True}
    finally:
        service._job_lock.release()
    assert calls == [1]


def test_second_server_pipe_in_use(svc, servers):
    from tapesmith.ipc.pipe import PipeInUse
    start, _client = servers
    service, _t = svc()
    first = start(service)
    other = DaemonServer(service, name=first.name)
    with pytest.raises(PipeInUse):
        other.start()


def test_anfrage_mit_sprache_liefert_meldungen_in_ihr(svc, servers):
    """Das optionale Feld `lang` einer Anfrage (CLI mit TAPESMITH_LANG=en) gilt für die Meldungen."""
    start, _client = servers
    service, _t = svc()
    server = start(service)
    a, _b = memory_channel_pair()
    en = server.dispatch(a, {"type": "request", "id": 2, "method": "gibtsnicht", "params": {}, "lang": "en"})
    de = server.dispatch(a, {"type": "request", "id": 3, "method": "gibtsnicht", "params": {}})
    assert en["ok"] is False and de["ok"] is False
    assert en["error"]["message"] == "Field 'method' in request message must be a known method"
    assert de["error"]["message"] == "Feld 'method' in request-Nachricht muss eine bekannte Methode sein"
