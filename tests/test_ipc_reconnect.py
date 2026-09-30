"""DaemonBackend überlebt einen Neustart des Druckdienstes (Absturz, `tapesmith daemon restart/stop`).

Ist der Kanal schon zu, bevor eine Anfrage raus geht, wird einmal neu verbunden (Listener neu
angemeldet) und wiederholt; ging der Druckauftrag schon raus, nie. Ist kein Dienst mehr erreichbar,
wird mit Hinweis direkt gedruckt. Nur Fakes, kein Prozess, keine Pipe."""

import threading

import pytest
from PIL import Image

from ipc_fakes import NO_REPLY, RestartableDaemon
from tapesmith.device.profile import load_profile
from tapesmith.ipc.backend import REASON_LOST, DaemonBackend, make_backend
from tapesmith.ipc.client import DaemonLost, DaemonNotSent
from tapesmith.jobs import JobMeta
from tapesmith.pipeline import PrintLabel, PrintOutcome, PrintRequest

P = load_profile()
NO_SPAWN = {"daemon": {"spawn": False}}


def make_request():
    return PrintRequest(labels=(PrintLabel(Image.new("1", (P.head_dots, 80), 255)),),
                        meta=JobMeta(source="gui", kind="text", title="T"))


class FakeLocal:
    kind = "local"

    def __init__(self, reason):
        self.fallback_reason = reason
        self.requests = []
        self.listeners = []

    def execute(self, request, **kw):
        self.requests.append(request)
        return PrintOutcome("ok", None, history_id=99)

    def add_listener(self, event, callback):
        self.listeners.append((event, callback))

    def remove_listener(self, event, callback):
        self.listeners.remove((event, callback))

    def state_info(self):
        return "lokal"

    def queue_ops(self):
        return None

    def close(self):
        pass


@pytest.fixture
def daemon():
    d = RestartableDaemon()
    yield d
    d.close()


def backend_for(daemon, cfg=None, locals_=None):
    locals_ = locals_ if locals_ is not None else []

    def local(reason):
        backend = FakeLocal(reason)
        locals_.append(backend)
        return backend

    backend = make_backend(dict(cfg or NO_SPAWN), P, client="gui", local_factory=local, env={},
                           connector=daemon.connector)
    assert isinstance(backend, DaemonBackend)
    return backend


def wait_closed(client):
    for _ in range(200):
        if client.closed:
            return
        threading.Event().wait(0.01)
    raise AssertionError("alter Client nicht geschlossen")


def test_closed_client_raises_not_sent(daemon):
    client = daemon.current.client()
    daemon.stop()
    wait_closed(client)
    with pytest.raises(DaemonNotSent, match="nicht gesendet"):
        client.call("ping")


def test_lost_after_send_is_not_not_sent(daemon):
    daemon.current.handlers["print"] = lambda s, p: (s.close(), NO_REPLY)[1]
    client = daemon.current.client()
    with pytest.raises(DaemonLost) as info:
        client.call("print", {}, timeout=None)
    assert not isinstance(info.value, DaemonNotSent)


def test_print_after_restart_reconnects_and_reregisters_listeners(daemon):
    backend = backend_for(daemon)
    states = []
    backend.add_listener("state", states.append)
    first = daemon.current
    assert backend.execute(make_request()).status == "ok"
    old_client = backend.client
    second = daemon.restart()
    wait_closed(old_client)

    outcome = backend.execute(make_request())
    assert outcome.status == "ok" and outcome.history_id == 42
    assert len(first.calls("print")) == 1
    assert len(second.calls("print")) == 1
    assert backend.kind == "daemon" and backend.client is not old_client

    second.emit("state", {"state": "verbunden", "transport": "COM4", "last_error": None, "leased": False})
    for _ in range(200):
        if states:
            break
        threading.Event().wait(0.01)
    assert [s.state for s in states] == ["verbunden"]
    backend.close()


def test_restart_without_waiting_for_reader(daemon):
    """Auch wenn der Lese-Thread den Abbruch noch nicht bemerkt hat: send scheitert -> neu verbinden."""
    backend = backend_for(daemon)
    daemon.restart()
    assert backend.execute(make_request()).status == "ok"
    assert len(daemon.current.calls("print")) == 1
    backend.close()


def test_queries_and_queue_ops_after_restart(daemon):
    backend = backend_for(daemon)
    old_client = backend.client
    daemon.restart()
    wait_closed(old_client)
    assert backend.state_info().state == "getrennt"
    old_client = backend.client
    daemon.restart()
    wait_closed(old_client)
    assert backend.queue_ops().list().jobs == ()
    backend.close()


def test_lost_after_send_is_not_repeated(daemon):
    daemon.current.handlers["print"] = lambda s, p: (s.close(), NO_REPLY)[1]
    backend = backend_for(daemon)
    daemon_before = daemon.current
    with pytest.raises(DaemonLost):
        backend.execute(make_request())
    assert len(daemon_before.calls("print")) == 1
    assert daemon.connects == 1           # kein zweiter Verbindungsversuch
    backend.close()


def test_stopped_daemon_falls_back_to_local_with_notice(daemon):
    locals_ = []
    backend = backend_for(daemon, locals_=locals_)
    seen = []
    backend.add_listener("warning", seen.append)
    old_client = backend.client
    daemon.stop()
    wait_closed(old_client)
    warnings = []
    outcome = backend.execute(make_request(), on_warning=warnings.append)
    assert outcome.history_id == 99
    assert warnings == [REASON_LOST]
    assert backend.kind == "local" and backend.fallback_reason == REASON_LOST
    assert len(locals_) == 1 and len(locals_[0].requests) == 1
    assert locals_[0].listeners == [("warning", seen.append)]
    assert backend.state_info() == "lokal"
    assert backend.queue_ops() is None
    backend.execute(make_request())
    assert len(locals_) == 1 and len(locals_[0].requests) == 2


def test_stopped_daemon_is_respawned_when_allowed(daemon):
    spawned = []

    def launcher(cfg, *, client):
        spawned.append(client)
        daemon.start()
        return daemon.connector(client=client)

    backend = make_backend({}, P, client="tray", local_factory=FakeLocal, env={},
                           connector=daemon.connector, launcher=launcher)
    old_client = backend.client
    daemon.stop()
    wait_closed(old_client)
    assert backend.execute(make_request()).status == "ok"
    assert spawned == ["tray"]
    assert len(daemon.current.calls("print")) == 1
    backend.close()


def test_without_reconnect_raises_not_sent(daemon):
    backend = DaemonBackend(daemon.current.client(), planner=lambda r: None)
    old_client = backend.client
    daemon.stop()
    wait_closed(old_client)
    with pytest.raises(DaemonNotSent):
        backend.execute(make_request())


def test_fallback_notice_in_outcome_without_warning_callback(daemon):
    backend = backend_for(daemon)
    old_client = backend.client
    daemon.stop()
    wait_closed(old_client)
    outcome = backend.execute(make_request())
    assert outcome.warnings == [REASON_LOST]
