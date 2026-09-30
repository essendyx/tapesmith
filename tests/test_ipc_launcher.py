import pytest

from tapesmith import launch
from tapesmith.ipc.launcher import daemon_running, ensure_daemon
from tapesmith.ipc.pipe import DaemonUnavailable


class FakeClient:
    def __init__(self, ping_error=None):
        self.closed = False
        self.ping_error = ping_error
        self.calls = []

    def call(self, method, params=None, *, timeout=30.0):
        self.calls.append(method)
        if self.ping_error:
            raise self.ping_error
        return {"pid": 1}

    def close(self):
        self.closed = True


def scripted_connector(results):
    attempts = []

    def connector(**kw):
        attempts.append(kw)
        item = results.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    return connector, attempts


def test_ensure_daemon_spawns_once_and_polls():
    client = FakeClient()
    connector, attempts = scripted_connector(
        [DaemonUnavailable("nein"), DaemonUnavailable("noch nicht"), client])
    spawned, slept = [], []
    result = ensure_daemon({}, client="gui", spawn=lambda argv: spawned.append(list(argv)) or 1234,
                           connector=connector, sleep=slept.append, clock=lambda: 0.0)
    assert result is client
    assert spawned == [launch.app_argv("daemon")]
    assert len(attempts) == 3
    assert all(a["client"] == "gui" for a in attempts)
    assert slept == [0.2]


def test_ensure_daemon_already_running_does_not_spawn():
    client = FakeClient()
    connector, _ = scripted_connector([client])
    assert ensure_daemon({}, spawn=lambda argv: pytest.fail("kein Start erwartet"), connector=connector) is client


def test_ensure_daemon_times_out_with_log_hint():
    now = [0.0]

    def connector(**kw):
        raise DaemonUnavailable("nie")

    def sleep(seconds):
        now[0] += seconds

    spawned = []
    with pytest.raises(DaemonUnavailable, match="daemon.log"):
        ensure_daemon({}, spawn=lambda argv: spawned.append(argv) or 1, connector=connector, sleep=sleep,
                      clock=lambda: now[0], timeout_s=1.0)
    assert len(spawned) == 1
    assert now[0] >= 1.0


def test_ensure_daemon_uses_configured_timeout_and_argv():
    now = [0.0]

    def connector(**kw):
        raise DaemonUnavailable("nie")

    def sleep(seconds):
        now[0] += seconds

    spawned = []
    with pytest.raises(DaemonUnavailable):
        ensure_daemon({"daemon": {"start_timeout_s": 0.5}}, spawn=lambda argv: spawned.append(argv) or 1,
                      argv=["p12d.exe"], connector=connector, sleep=sleep, clock=lambda: now[0])
    assert spawned == [["p12d.exe"]]
    assert 0.5 <= now[0] < 1.0


def test_ensure_daemon_spawn_failure_is_unavailable():
    def connector(**kw):
        raise DaemonUnavailable("nie")

    def spawn(argv):
        raise RuntimeError("Start fehlgeschlagen: keine Datei")

    with pytest.raises(DaemonUnavailable, match="startet nicht"):
        ensure_daemon({}, spawn=spawn, connector=connector)


def test_daemon_running():
    client = FakeClient()
    assert daemon_running(connector=lambda **kw: client) is True
    assert client.calls == ["ping"] and client.closed

    def unavailable(**kw):
        raise DaemonUnavailable("nein")

    assert daemon_running(connector=unavailable) is False
    broken = FakeClient(ping_error=RuntimeError("kaputt"))
    assert daemon_running(connector=lambda **kw: broken) is False
    assert broken.closed
