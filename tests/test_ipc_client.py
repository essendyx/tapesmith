import threading
import time

import pytest

from ipc_fakes import HOME, NO_REPLY, FakeServer
from tapesmith.ipc import protocol
from tapesmith.ipc.client import DaemonClient, DaemonLost
from tapesmith.ipc.protocol import IpcError, ProtocolError
from tapesmith.lock import PrinterBusy


@pytest.fixture
def server():
    srv = FakeServer()
    yield srv
    srv.close()


def test_call_returns_result_and_maps_errors(server):
    server.handlers["ping"] = lambda s, p: {"pid": 4711, "uptime_s": 1.0, "clients": 1, "version": "9.9"}

    def busy(s, p):
        raise PrinterBusy("Drucker belegt (Test)")

    server.handlers["lease"] = busy
    client = server.client()
    try:
        assert client.call("ping")["pid"] == 4711
        assert client.server_pid == 4711
        assert client.server_version == "9.9"
        with pytest.raises(PrinterBusy, match="belegt"):
            client.call("lease", {"timeout_s": 1.0})
    finally:
        client.close()
    assert client.closed


def test_concurrent_calls_get_their_own_answers(server):
    release = threading.Event()

    def slow_state(s, p):
        release.wait(2)
        return {"state": "verbunden", "transport": "COM4", "last_error": None, "leased": False}

    server.handlers["state"] = slow_state
    server.handlers["ping"] = lambda s, p: {"pid": 1, "uptime_s": 0.0, "clients": 2, "version": "x"}
    client = server.client()
    results = {}

    def get_state():
        results["state"] = client.call("state")

    t = threading.Thread(target=get_state)
    t.start()
    time.sleep(0.05)
    results["ping"] = client.call("ping")      # kommt an, obwohl state noch hängt
    assert "state" not in results
    release.set()
    t.join(2)
    client.close()
    assert results["ping"]["clients"] == 2
    assert results["state"]["transport"] == "COM4"


def test_listeners_receive_events_and_faulty_listener_is_isolated(server):
    client = server.client()
    got_job, got_all, got_after = [], [], []
    done = threading.Event()

    def bad(data):
        raise RuntimeError("kaputt")

    client.add_listener("job", bad)
    client.add_listener("job", got_job.append)
    client.add_listener("*", got_all.append)

    def after(data):
        got_after.append(data)
        done.set()

    client.add_listener("queue", after)
    server.emit("job", {"job_key": "k1", "phase": "läuft", "status": None, "source": "cli",
                        "title": "x", "queue_id": None})
    server.emit("queue", {})
    assert done.wait(2)
    assert got_job == [{"job_key": "k1", "phase": "läuft", "status": None, "source": "cli",
                        "title": "x", "queue_id": None}]
    assert [e["event"] for e in got_all] == ["job", "queue"]
    assert got_after == [{}]
    client.remove_listener("job", got_job.append)
    client.close()


def test_channel_closed_during_call_raises_daemon_lost(server):
    server.handlers["print"] = lambda s, p: (s.close(), NO_REPLY)[1]
    client = server.client()
    with pytest.raises(DaemonLost, match="Verlauf"):
        client.call("print", {"job_key": "k", "request": {}, "enqueue_on_offline": False}, timeout=None)
    assert client.closed
    with pytest.raises(DaemonLost):
        client.call("ping")


def test_timeout_raises_ipc_error(server):
    server.handlers["state"] = lambda s, p: NO_REPLY
    client = server.client()
    try:
        with pytest.raises(IpcError, match="antwortet nicht \\(state\\)") as info:
            client.call("state", timeout=0.1)
        assert not isinstance(info.value, DaemonLost)
    finally:
        client.close()


def test_connect_performs_handshake_and_rejects_other_protocol():
    ok = FakeServer()
    client = DaemonClient.connect(client="cli", home=HOME, connector=ok.connector)
    assert client.server_pid == 4711
    assert ok.hellos[0]["client"] == "cli" and ok.hellos[0]["home"] == HOME
    client.close()
    ok.close()

    bad = FakeServer(handshake_error=protocol.error_message("protocol", "Protokoll 2 nicht unterstützt"))
    with pytest.raises(ProtocolError, match="Protokoll 2"):
        DaemonClient.connect(client="cli", home=HOME, connector=bad.connector)


def test_connect_rejects_welcome_with_protocol_2():
    srv = FakeServer()
    srv.welcome = dict(srv.welcome, protocol=2)
    with pytest.raises(ProtocolError):
        DaemonClient.connect(client="gui", home=HOME, connector=srv.connector)
    srv.close()
