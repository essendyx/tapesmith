"""Named Pipe des Druckdienstes: echte lokale Pipes mit je Test eindeutigem Namen (home_key)."""

import base64
import os
import threading
import time
import uuid

import pytest

from tapesmith.ipc import pipe as pipe_mod
from tapesmith.ipc import protocol
from tapesmith.ipc.pipe import (
    ChannelClosed,
    DaemonUnavailable,
    IpcError,
    PipeInUse,
    PipeServer,
    ProtocolError,
    client_handshake,
    connect,
    current_user_sid,
    daemon_mutex_name,
    home_key,
    memory_channel_pair,
    pipe_dacl_sids,
    pipe_name,
    server_handshake,
)
from tapesmith.ipc.protocol import event, request, response_ok


def echo_handler(ch):
    while True:
        try:
            msg = ch.recv()
        except ChannelClosed:
            return
        ch.send(msg)


def wait_for(cond, timeout=2.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return cond()


def test_home_key_and_names(tmp_path, monkeypatch):
    a = home_key()
    assert a == home_key()
    assert len(a) == 12 and all(c in "0123456789abcdef" for c in a)
    assert home_key(tmp_path / "x") != home_key(tmp_path / "y")
    assert pipe_name() == r"\\.\pipe\tapesmith-" + a
    assert daemon_mutex_name() == "Local\\Tapesmith.Daemon." + a
    monkeypatch.setenv("TAPESMITH_PIPE_NAME", r"\\.\pipe\eigener")
    monkeypatch.setenv("TAPESMITH_DAEMON_MUTEX", "Local\\Eigen")
    assert pipe_name() == r"\\.\pipe\eigener"
    assert daemon_mutex_name() == "Local\\Eigen"


def test_home_key_depends_on_user(monkeypatch):
    a = home_key()
    monkeypatch.setenv("USERNAME", "jemand-anders")
    assert home_key() != a


def test_exceptions_hierarchy():
    for cls in (DaemonUnavailable, ChannelClosed, PipeInUse, ProtocolError):
        assert issubclass(cls, IpcError)
    assert ProtocolError is protocol.ProtocolError


def test_echo_single_and_parallel_clients():
    server = PipeServer(pipe_name(), echo_handler)
    server.start()
    try:
        ch = connect(server.name, timeout_s=2)
        try:
            msg = request(1, "ping")
            ch.send(msg)
            assert ch.recv(timeout=2) == msg
        finally:
            ch.close()

        results = {}
        errors = []

        def client(n):
            try:
                c = connect(server.name, timeout_s=2)
                try:
                    for i in range(1, 6):
                        c.send(request(i, "cancel", {"job_key": f"c{n}-{i}"}))
                        got = c.recv(timeout=2)
                        assert got["params"]["job_key"] == f"c{n}-{i}"
                    results[n] = True
                finally:
                    c.close()
            except Exception as exc:  # pragma: no cover (nur Diagnose)
                errors.append(exc)

        threads = [threading.Thread(target=client, args=(n,)) for n in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(5)
        assert not errors
        assert results == {0: True, 1: True, 2: True}
    finally:
        server.stop()


def test_large_message():
    payload = base64.b64encode(os.urandom(3_750_000)).decode("ascii")  # 5 MB Text
    assert len(payload) == 5_000_000
    server = PipeServer(pipe_name(), echo_handler)
    server.start()
    try:
        ch = connect(server.name)
        try:
            msg = event("warning", {"job_key": "gross", "text": payload})
            ch.send(msg)
            got = ch.recv(timeout=10)
            assert got["data"]["text"] == payload
        finally:
            ch.close()
    finally:
        server.stop()


def test_recv_timeout_and_server_close():
    closing = threading.Event()

    def handler(ch):
        closing.wait(30)
        ch.close()

    server = PipeServer(pipe_name(), handler)
    server.start()
    try:
        ch = connect(server.name)
        try:
            start = time.monotonic()
            assert ch.recv(timeout=0.05) is None
            assert time.monotonic() - start < 5.0      # der Handler schweigt bis zu 30 s
            closing.set()
            with pytest.raises(ChannelClosed):
                ch.recv(timeout=2)
        finally:
            ch.close()
            ch.close()  # idempotent
        assert ch.closed
        with pytest.raises(ChannelClosed):
            ch.recv(timeout=0.01)
    finally:
        server.stop()


def test_close_wakes_blocking_recv():
    server = PipeServer(pipe_name(), echo_handler)
    server.start()
    try:
        ch = connect(server.name)
        outcome = []

        def reader():
            try:
                ch.recv()
            except ChannelClosed:
                outcome.append("closed")

        t = threading.Thread(target=reader)
        t.start()
        time.sleep(0.1)
        start = time.monotonic()
        ch.close()
        t.join(30)
        assert not t.is_alive()
        assert outcome == ["closed"]
        assert time.monotonic() - start < 5.0
    finally:
        server.stop()


def test_second_server_in_use():
    name = pipe_name()
    first = PipeServer(name, echo_handler)
    first.start()
    try:
        second = PipeServer(name, echo_handler)
        with pytest.raises(PipeInUse):
            second.start()
    finally:
        first.stop()
    third = PipeServer(name, echo_handler)
    third.start()
    try:
        ch = connect(name)
        ch.send(request(1, "ping"))
        assert ch.recv(timeout=2)["method"] == "ping"
        ch.close()
    finally:
        third.stop()


def test_connect_missing_pipe():
    start = time.monotonic()
    with pytest.raises(DaemonUnavailable):
        connect("\\\\.\\pipe\\tapesmith-gibtsnicht-" + uuid.uuid4().hex, timeout_s=0.2)
    assert time.monotonic() - start < 5.0


def test_dacl_only_current_user():
    sid = current_user_sid()
    assert sid.startswith("S-1-5-")
    server = PipeServer(pipe_name(), echo_handler)
    server.start()
    try:
        sids = pipe_dacl_sids(server.name)
        assert sids == [sid]
        assert "S-1-1-0" not in sids and "S-1-5-32-544" not in sids
    finally:
        server.stop()


def test_stop_closes_everything():
    server = PipeServer(pipe_name(), echo_handler)
    server.start()
    try:
        clients = [connect(server.name) for _ in range(2)]
        for i, c in enumerate(clients, 1):
            c.send(request(i, "ping"))
            assert c.recv(timeout=2)["id"] == i
        assert wait_for(lambda: server.active_channels() == 2)
        start = time.monotonic()
        server.stop()
        assert time.monotonic() - start < 10.0
        assert server.active_channels() == 0
        for c in clients:
            with pytest.raises(ChannelClosed):
                c.recv(timeout=2)
            c.close()
        server.stop()  # idempotent
    finally:
        server.stop()
    assert not [t for t in threading.enumerate() if t.name.startswith("tapesmith-pipe")]


def test_send_after_peer_closed():
    a, b = memory_channel_pair()
    b.close()
    with pytest.raises(ChannelClosed):
        a.recv(timeout=0.1)
    with pytest.raises(ChannelClosed):
        a.send(request(1, "ping"))
    a.close()
    assert a.closed and b.closed


def test_memory_channel_semantics():
    a, b = memory_channel_pair()
    msg = response_ok(1, {"text": "Größe"})
    a.send(msg)
    got = b.recv(timeout=1)
    assert got == msg and got is not msg
    assert b.recv(timeout=0.05) is None
    a.send({"type": "unbekannt"})       # wie bei der Pipe: erst der Empfänger prüft die Zeile
    with pytest.raises(ProtocolError):
        b.recv(timeout=1)

    def later():
        time.sleep(0.05)
        b.close()

    t = threading.Thread(target=later)
    t.start()
    with pytest.raises(ChannelClosed):
        b.recv()
    t.join()


def _run_server_handshake(ch, box, **kw):
    try:
        box["hello"] = server_handshake(ch, **kw)
    except Exception as exc:
        box["error"] = exc


def test_handshake_memory():
    client, server = memory_channel_pair()
    box = {}
    t = threading.Thread(target=_run_server_handshake, args=(server, box))
    t.start()
    welcome = client_handshake(client, "test")
    t.join(2)
    assert welcome["type"] == "welcome" and welcome["home"] == home_key()
    assert box["hello"]["client"] == "test"
    assert box["hello"]["pid"] == os.getpid()


def test_handshake_wrong_protocol(monkeypatch):
    real = pipe_mod.hello
    monkeypatch.setattr(pipe_mod, "hello", lambda *a, **k: {**real(*a, **k), "protocol": 2})
    client, server = memory_channel_pair()
    box = {}
    t = threading.Thread(target=_run_server_handshake, args=(server, box))
    t.start()
    with pytest.raises(ProtocolError, match="Protokoll"):
        client_handshake(client, "test")
    t.join(2)
    assert isinstance(box["error"], ProtocolError)
    assert "Protokoll 2 nicht unterstützt (Dienst spricht 1)" in str(box["error"])


def test_handshake_wrong_home():
    client, server = memory_channel_pair()
    box = {}
    t = threading.Thread(target=_run_server_handshake, args=(server, box))
    t.start()
    with pytest.raises(ProtocolError):
        client_handshake(client, "test", home="anderes-home")
    t.join(2)
    assert isinstance(box["error"], ProtocolError)


def test_handshake_timeout():
    client, _server = memory_channel_pair()
    start = time.monotonic()
    with pytest.raises(DaemonUnavailable):
        client_handshake(client, "test", timeout_s=0.1)
    assert time.monotonic() - start < 5.0


def test_handshake_over_pipe():
    seen = []

    def handler(ch):
        try:
            seen.append(server_handshake(ch))
        except ProtocolError:
            return
        echo_handler(ch)

    server = PipeServer(pipe_name(), handler)
    server.start()
    try:
        ch = connect(server.name)
        try:
            welcome = client_handshake(ch, "cli")
            assert welcome["protocol"] == 1 and welcome["home"] == home_key()
            ch.send(request(7, "state"))
            assert ch.recv(timeout=2)["id"] == 7
        finally:
            ch.close()
        assert seen and seen[0]["client"] == "cli"

        bad = connect(server.name)
        try:
            with pytest.raises(ProtocolError):
                client_handshake(bad, "cli", home="falsch")
        finally:
            bad.close()
    finally:
        server.stop()


def test_channels_satisfy_protocol():
    from tapesmith.ipc.pipe import Channel

    a, b = memory_channel_pair()
    assert isinstance(a, Channel) and isinstance(b, Channel)
    server = PipeServer(pipe_name(), echo_handler)
    server.start()
    try:
        with connect(server.name) as ch:
            assert isinstance(ch, Channel)
            assert not ch.closed
        assert ch.closed
    finally:
        server.stop()
