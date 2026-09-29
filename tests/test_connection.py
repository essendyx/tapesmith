"""Verbindungsmanager: Verbindung bei Bedarf, Leerlauf-Trennung, Offline-Erkennung."""

import threading
import time

import pytest

from tapesmith import connection
from tapesmith.connection import ConnectionManager, ConnectionState, PrinterOffline
from tapesmith.device.profile import load_profile
from tapesmith.lock import PrinterBusy, PrintLock
from tapesmith.printer import PrinterSession
from tapesmith.transport import resolve
from tapesmith.transport.base import ConnectTimeout, MemoryTransport, TransportError

QUERY = bytes.fromhex("1f1108")
ANSWER = bytes.fromhex("1a044b")


class FakeLock:
    """Merkt sich, in welchem Thread gesperrt/freigegeben wurde."""

    def __init__(self, log):
        self.log = log

    def __enter__(self):
        self.log.append(("enter", threading.get_ident()))
        return self

    def __exit__(self, *e):
        self.log.append(("exit", threading.get_ident()))
        return False


class FakeTransport(MemoryTransport):
    def __init__(self, open_delay=0.0, open_error=None, block: threading.Event | None = None):
        super().__init__({QUERY: ANSWER})
        self.open_delay = open_delay
        self.open_error = open_error
        self.block = block
        self.open_threads: list[int] = []
        self.close_threads: list[int] = []

    def open(self) -> None:
        self.open_threads.append(threading.get_ident())
        if self.block is not None:
            self.block.wait()
        if self.open_delay:
            time.sleep(self.open_delay)
        if self.open_error is not None:
            raise self.open_error
        super().open()
        self.closed = False

    def close(self) -> None:
        self.close_threads.append(threading.get_ident())
        super().close()


class FakeClock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


class Factory:
    def __init__(self, make=lambda: FakeTransport()):
        self.make = make
        self.made: list[FakeTransport] = []

    def __call__(self):
        t = self.make()
        self.made.append(t)
        return t


@pytest.fixture
def managers():
    created = []

    def make(factory, **kw):
        kw.setdefault("lock_factory", lambda: FakeLock([]))
        kw.setdefault("sleep", lambda s: None)
        m = ConnectionManager(factory, load_profile(), **kw)
        created.append(m)
        return m

    yield make
    for m in created:
        m.close()


def wait_for(pred, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(0.01)
    return pred()


def query(s):
    return s.query("1f1108")


def test_run_connects_lazily_and_reuses_connection(managers):
    factory = Factory()
    m = managers(factory)
    assert m.state is ConnectionState.DISCONNECTED
    assert factory.made == []
    assert m.run(query) == ANSWER
    assert m.run(query) == ANSWER
    assert len(factory.made) == 1
    assert m.state is ConnectionState.CONNECTED


def test_lock_acquired_and_released_in_same_worker_thread(managers):
    log = []
    factory = Factory()
    m = managers(factory, lock_factory=lambda: FakeLock(log))
    m.run(query)
    m.disconnect()
    assert [e[0] for e in log] == ["enter", "exit"]
    assert log[0][1] == log[1][1] != threading.get_ident()
    t = factory.made[0]
    assert t.open_threads == t.close_threads == [log[0][1]]
    assert m.state is ConnectionState.DISCONNECTED


def test_idle_timeout_disconnects(managers):
    factory = Factory()
    m = managers(factory, idle_timeout_s=0.1)
    m.run(query)
    assert wait_for(lambda: m.state is ConnectionState.DISCONNECTED)
    assert factory.made[0].closed


def test_idle_zero_disconnects_after_each_run(managers):
    factory = Factory()
    m = managers(factory, idle_timeout_s=0)
    assert m.run(query) == ANSWER
    assert m.state is ConnectionState.DISCONNECTED
    assert factory.made[0].closed
    m.run(query)
    assert len(factory.made) == 2


def test_connect_timeout_is_fast_and_sets_offline(managers):
    block = threading.Event()
    factory = Factory(lambda: FakeTransport(block=block))
    m = managers(factory, connect_timeout_s=0.2)
    try:
        start = time.monotonic()
        with pytest.raises(PrinterOffline, match="nicht erreichbar"):
            m.connect()
        assert time.monotonic() - start < 1.0
        assert m.state is ConnectionState.OFFLINE
        assert isinstance(m.last_error, PrinterOffline)
        start = time.monotonic()
        with pytest.raises(PrinterOffline, match="offline"):
            m.run(query)
        assert time.monotonic() - start < 0.05
        m.preconnect()
        time.sleep(0.05)
        assert len(factory.made) == 1
    finally:
        block.set()
        m.close()


def test_printer_offline_is_connect_timeout():
    assert issubclass(PrinterOffline, ConnectTimeout)


def test_backoff_expires_with_clock(managers):
    block = threading.Event()
    clock = FakeClock()
    factory = Factory(lambda: FakeTransport(block=block))
    m = managers(factory, connect_timeout_s=0.1, offline_backoff_s=10, clock=clock)
    try:
        with pytest.raises(PrinterOffline):
            m.connect()
        clock.now += 5
        with pytest.raises(PrinterOffline, match="vor 5 s"):
            m.connect()
        clock.now += 6
        block.set()
        m.connect()          # Backoff abgelaufen, verspäteter Open hat inzwischen verbunden
        assert m.state is ConnectionState.CONNECTED
    finally:
        block.set()


def test_force_bypasses_backoff(managers):
    factory = Factory(lambda: FakeTransport(open_delay=0.3))
    m = managers(factory, connect_timeout_s=0.2, offline_backoff_s=10)
    start = time.monotonic()
    with pytest.raises(PrinterOffline):
        m.connect()
    assert time.monotonic() - start < 0.28
    assert m.state is ConnectionState.OFFLINE
    start = time.monotonic()
    with pytest.raises(PrinterOffline):
        m.run(query)
    assert time.monotonic() - start < 0.05
    m.connect(force=True, timeout=1.0)
    assert m.state is ConnectionState.CONNECTED
    assert len(factory.made) == 1


def test_late_open_success_keeps_connection(managers):
    block = threading.Event()
    factory = Factory(lambda: FakeTransport(block=block))
    m = managers(factory, connect_timeout_s=0.1)
    with pytest.raises(PrinterOffline):
        m.connect()
    block.set()
    assert wait_for(lambda: m.state is ConnectionState.CONNECTED)
    assert m.run(query) == ANSWER
    assert len(factory.made) == 1


def test_timed_out_run_does_not_execute_job_later(managers):
    block = threading.Event()
    factory = Factory(lambda: FakeTransport(block=block))
    m = managers(factory, connect_timeout_s=0.1)
    ran = []
    with pytest.raises(PrinterOffline):
        m.run(lambda s: ran.append(1))
    block.set()
    assert wait_for(lambda: m.state is ConnectionState.CONNECTED)
    m.disconnect()
    assert ran == []


def test_open_error_releases_lock_in_worker_and_sets_error(managers):
    log = []
    factory = Factory(lambda: FakeTransport(open_error=TransportError("kaputt")))
    m = managers(factory, lock_factory=lambda: FakeLock(log))
    with pytest.raises(TransportError, match="kaputt"):
        m.run(query)
    assert m.state is ConnectionState.ERROR
    assert [e[0] for e in log] == ["enter", "exit"]
    assert log[0][1] == log[1][1] != threading.get_ident()


def test_busy_lock_sets_busy_and_raises(managers):
    def busy():
        raise PrinterBusy("belegt")

    factory = Factory()
    m = managers(factory, lock_factory=busy)
    with pytest.raises(PrinterBusy):
        m.run(query)
    assert m.state is ConnectionState.BUSY
    assert factory.made == []


def test_transport_error_in_job_drops_connection(managers):
    factory = Factory()
    m = managers(factory)

    def broken(s):
        raise TransportError("weg")

    with pytest.raises(TransportError, match="weg"):
        m.run(broken)
    assert factory.made[0].closed
    assert m.state is ConnectionState.DISCONNECTED
    m.run(query)
    assert len(factory.made) == 2


def test_fn_exception_other_than_transport_keeps_connection(managers):
    factory = Factory()
    m = managers(factory)

    def broken(s):
        raise ValueError("falsch")

    with pytest.raises(ValueError):
        m.run(broken)
    assert m.state is ConnectionState.CONNECTED
    assert not factory.made[0].closed
    m.run(query)
    assert len(factory.made) == 1


def test_preconnect_is_non_blocking(managers):
    factory = Factory(lambda: FakeTransport(open_delay=0.3))
    m = managers(factory)
    start = time.monotonic()
    m.preconnect()
    assert time.monotonic() - start < 0.05
    m.preconnect()       # zweites Vorverbinden während des Aufbaus: kein neuer Versuch
    assert m.run(query) == ANSWER
    assert len(factory.made) == 1


def test_runs_are_serialised(managers):
    m = managers(Factory())
    windows = []

    def work(s):
        start = time.monotonic()
        time.sleep(0.1)
        windows.append((start, time.monotonic()))

    threads = [threading.Thread(target=m.run, args=(work,)) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(2)
    assert len(windows) == 2
    (a0, a1), (b0, b1) = sorted(windows)
    assert a1 <= b0


def test_queued_run_waits_for_long_job_without_offline(managers):
    """Wartezeit hinter einem laufenden Druck zählt nicht zum Verbindungs-Timeout."""
    m = managers(Factory(), connect_timeout_s=0.1)
    started = threading.Event()

    def long_job(s):
        started.set()
        time.sleep(0.3)
        return "lang"

    results = []
    t = threading.Thread(target=lambda: results.append(m.run(long_job)))
    t.start()
    assert started.wait(1)
    assert m.run(query) == ANSWER
    t.join(2)
    assert results == ["lang"]


def test_on_state_sequence(managers):
    seen = []
    m = managers(Factory(), on_state=seen.append)
    m.run(query)
    m.disconnect()
    assert seen == [ConnectionState.CONNECTING, ConnectionState.CONNECTED,
                    ConnectionState.DISCONNECTED]


def test_on_state_exceptions_are_swallowed(managers):
    def boom(state):
        raise RuntimeError("Callback kaputt")

    m = managers(Factory(), on_state=boom)
    assert m.run(query) == ANSWER
    assert m.state is ConnectionState.CONNECTED


def test_held_transport_ignores_open_close(managers):
    factory = Factory()
    m = managers(factory)

    def use(session):
        assert isinstance(session, PrinterSession)
        with session:
            answer = session.query("1f1108")
        assert session.transport.name == "memory"
        return answer

    assert m.run(use) == ANSWER
    assert not factory.made[0].closed
    assert m.run(query) == ANSWER
    assert len(factory.made) == 1


def test_session_factory_gets_sleep(managers):
    calls = []

    def session_factory(transport, profile, lock=None, sleep=None):
        calls.append(sleep)
        return PrinterSession(transport, profile, lock=lock, sleep=sleep)

    sleeper = lambda s: None  # noqa: E731
    m = managers(Factory(), session_factory=session_factory, sleep=sleeper)
    m.run(query)
    assert calls == [sleeper]


def test_close_is_idempotent(managers):
    factory = Factory()
    m = managers(factory)
    m.run(query)
    worker = m._worker
    m.close()
    m.close()
    assert factory.made[0].closed
    assert m.state is ConnectionState.DISCONNECTED
    assert not worker.is_alive()
    with pytest.raises(TransportError, match="geschlossen"):
        m.run(query)


def test_close_without_worker_and_context_manager():
    with ConnectionManager(Factory(), load_profile(), lock_factory=lambda: FakeLock([])) as m:
        assert m.state is ConnectionState.DISCONNECTED
    m.close()


def test_disconnect_without_worker_is_noop(managers):
    m = managers(Factory())
    m.disconnect()
    assert m.state is ConnectionState.DISCONNECTED


def test_worker_thread_name_and_daemon(managers):
    m = managers(Factory())
    m.run(query)
    worker = m._worker
    assert worker.name == "P12-Verbindung"
    assert worker.daemon
    m.close()
    assert not worker.is_alive()


def test_real_print_lock_released_by_worker(managers):
    m = managers(Factory(), lock_factory=PrintLock)
    assert m.run(query) == ANSWER
    with pytest.raises(PrinterBusy):
        with PrintLock():
            pass
    m.disconnect()
    with PrintLock():
        pass


def test_open_transport_passes_open_timeout(monkeypatch):
    created = []

    class FakeSerial:
        def __init__(self, port, open_timeout=8.0):
            created.append((port, open_timeout))
            self.name = port

    monkeypatch.setattr(resolve, "SerialTransport", FakeSerial)
    resolve.open_transport("COM4", "001122334455", open_timeout=5.0)
    resolve.open_transport("com:COM5", "001122334455")
    reader = lambda: [("COM9", "001122334455", True)]  # noqa: E731
    monkeypatch.setattr(resolve, "find_outgoing_port", lambda mac, r: "COM9")
    resolve.open_transport("auto", "001122334455", reader=reader, open_timeout=3.0)
    assert created == [("COM4", 5.0), ("COM5", 8.0), ("COM9", 3.0)]


def test_module_exports():
    assert connection.ConnectionState.OFFLINE.value == "offline"
    assert connection.ConnectionState.BUSY.value == "belegt"


def _recorder():
    seen = []

    def on_state(state):
        seen.append((state, threading.current_thread().name))

    return seen, on_state


def test_on_state_offline_timeout_is_reported_from_worker(managers):
    block = threading.Event()
    seen, on_state = _recorder()
    m = managers(Factory(lambda: FakeTransport(block=block)), connect_timeout_s=0.1,
                 on_state=on_state)
    with pytest.raises(PrinterOffline):
        m.connect()
    assert m.state is ConnectionState.OFFLINE          # Zustand sofort sichtbar
    time.sleep(0.05)
    assert [s for s, _ in seen] == [ConnectionState.CONNECTING]  # Worker hängt noch im open
    block.set()
    assert wait_for(lambda: m.state is ConnectionState.CONNECTED)
    assert wait_for(lambda: len(seen) == 3)
    assert [s for s, _ in seen] == [ConnectionState.CONNECTING, ConnectionState.OFFLINE,
                                    ConnectionState.CONNECTED]
    assert {name for _, name in seen} == {"P12-Verbindung"}


def test_on_state_offline_reported_once_from_worker_when_open_fails_late(managers):
    block = threading.Event()
    seen, on_state = _recorder()
    m = managers(Factory(lambda: FakeTransport(block=block, open_error=ConnectTimeout("weg"))),
                 connect_timeout_s=0.1, on_state=on_state)
    with pytest.raises(PrinterOffline):
        m.connect()
    block.set()
    assert wait_for(lambda: len(seen) >= 2)
    time.sleep(0.05)
    assert [s for s, _ in seen] == [ConnectionState.CONNECTING, ConnectionState.OFFLINE]
    assert {name for _, name in seen} == {"P12-Verbindung"}
    assert m.state is ConnectionState.OFFLINE


def test_on_state_offline_from_preconnect_timeout_is_reported_from_worker(managers):
    block = threading.Event()
    seen, on_state = _recorder()
    m = managers(Factory(lambda: FakeTransport(block=block, open_error=ConnectTimeout("weg"))),
                 connect_timeout_s=0.1, on_state=on_state)
    m.preconnect()
    assert wait_for(lambda: m.state is ConnectionState.OFFLINE)
    block.set()
    assert wait_for(lambda: len(seen) >= 2)
    time.sleep(0.05)
    assert seen == [(ConnectionState.CONNECTING, "P12-Verbindung"),
                    (ConnectionState.OFFLINE, "P12-Verbindung")]
