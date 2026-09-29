import contextlib
import threading
from datetime import datetime

import pytest
from PIL import Image

from ipc_fakes import NO_REPLY, FakeServer
from tapesmith.device.profile import load_profile
from tapesmith.ipc import codec
from tapesmith.ipc.backend import (
    REASON_OTHER_VERSION,
    REASON_UNREACHABLE,
    DaemonBackend,
    LocalBackend,
    QueueSnapshot,
    Relay,
    local_planner,
    make_backend,
    use_daemon,
)
from tapesmith.ipc.client import DaemonLost
from tapesmith.ipc.codec import StateInfo, StatusReport
from tapesmith.ipc.pipe import DaemonUnavailable
from tapesmith.ipc.protocol import ProtocolError
from tapesmith.jobs import CancelToken, JobMeta
from tapesmith.pipeline import PrintLabel, PrintPipeline, PrintRequest, direct_runner
from tapesmith.printer import PrinterSession
from tapesmith.transport.base import MemoryTransport

P = load_profile()
NOW = datetime(2026, 9, 27, 12, 0, 0)
STATUS_OK = {
    bytes.fromhex("1f1108"): bytes.fromhex("1a044b"),
    bytes.fromhex("1f1111"): bytes.fromhex("1a0689"),
    bytes.fromhex("1f1112"): bytes.fromhex("1a0598"),
}
STATUS_LID_OPEN = {**STATUS_OK, bytes.fromhex("1f1112"): bytes.fromhex("1a0599")}


def make_request(rows=80):
    return PrintRequest(labels=(PrintLabel(Image.new("1", (P.head_dots, rows), 255)),),
                        meta=JobMeta(source="cli", kind="text", title="T"))


def outcome_dict(status="ok", **kw):
    data = {"status": status, "warnings": [], "reasons": [], "history_id": 42, "consumed_mm": 12.0,
            "results": [{"rows": 80, "rows_sent": 80, "waited_s": 0.1, "status": "ok"}],
            "printer_status": None, "error": None, "queue_id": None}
    data.update(kw)
    return data


@pytest.fixture
def server():
    srv = FakeServer()
    yield srv
    srv.close()


def daemon_backend(server):
    plans = []

    def planner(request):
        plan = local_planner({}, P)(request)
        plans.append(plan)
        return plan

    return DaemonBackend(server.client(), planner=planner), plans


# ---------- DaemonBackend ----------

def test_execute_filters_events_by_job_key(server):
    def do_print(s, params):
        key = params["job_key"]
        s.emit("progress", {"job_key": "fremd", "done": 1, "total": 9})
        s.emit("progress", {"job_key": key, "done": 40, "total": 80})
        s.emit("warning", {"job_key": "fremd", "text": "nicht meins"})
        s.emit("warning", {"job_key": key, "text": "Akku niedrig (15 %)"})
        s.emit("cut_pause", {"job_key": key, "state": "start", "done": 1, "total": 2, "seconds": 5.0})
        s.emit("cut_pause", {"job_key": "fremd", "state": "start", "done": 1, "total": 2, "seconds": 5.0})
        return outcome_dict(warnings=["Akku niedrig (15 %)"])

    server.handlers["print"] = do_print
    backend, plans = daemon_backend(server)
    progress, warnings, pauses = [], [], []
    outcome = backend.execute(make_request(), on_progress=lambda d, t: progress.append((d, t)),
                              on_warning=warnings.append,
                              on_cut_pause=lambda *a: pauses.append(a))
    backend.close()
    assert progress == [(40, 80)]
    assert warnings == ["Akku niedrig (15 %)"]
    assert pauses == [("start", 1, 2, 5.0)]
    assert outcome.status == "ok"
    assert outcome.history_id == 42
    assert outcome.plan is plans[-1]
    params = server.calls("print")[0]
    assert params["enqueue_on_offline"] is False
    assert codec.decode_request(params["request"]).meta.source == "cli"


def test_cancel_sends_exactly_one_cancel(server):
    cancelled = threading.Event()

    def do_print(s, params):
        cancelled.wait(3)
        return outcome_dict(status="abgebrochen")

    def do_cancel(s, params):
        cancelled.set()
        return {"cancelled": True}

    server.handlers["print"] = do_print
    server.handlers["cancel"] = do_cancel
    backend, _ = daemon_backend(server)
    token = CancelToken()
    threading.Timer(0.1, token.cancel).start()
    outcome = backend.execute(make_request(), cancel=token)
    backend.close()
    assert outcome.status == "abgebrochen"
    key = server.calls("print")[0]["job_key"]
    assert server.calls("cancel") == [{"job_key": key}]


def test_waiting_outcome_carries_queue_id(server):
    server.handlers["print"] = lambda s, p: outcome_dict(status="wartet", queue_id=4, history_id=None,
                                                         results=[])
    backend, _ = daemon_backend(server)
    outcome = backend.execute(make_request(), enqueue_on_offline=True)
    backend.close()
    assert outcome.status == "wartet"
    assert outcome.queue_id == 4
    assert server.calls("print")[0]["enqueue_on_offline"] is True


def test_lost_channel_during_print(server):
    server.handlers["print"] = lambda s, p: (s.close(), NO_REPLY)[1]
    backend, _ = daemon_backend(server)
    with pytest.raises(DaemonLost):
        backend.execute(make_request())


def test_lease_releases_even_on_exception(server):
    server.handlers["lease"] = lambda s, p: {"lease_id": "L1"}
    backend, _ = daemon_backend(server)
    with backend.lease(30):
        assert server.methods() == ["lease"]
    with pytest.raises(RuntimeError):
        with backend.lease():
            raise RuntimeError("Befehl scheitert")
    backend.close()
    assert server.methods() == ["lease", "release", "lease", "release"]
    assert server.calls("lease")[0] == {"timeout_s": 30.0}
    assert server.calls("release") == [{"lease_id": "L1"}, {"lease_id": "L1"}]


def test_queue_ops_over_daemon(server):
    job = {"id": 3, "created": "2026-09-27T11:00:00", "source": "cli", "title": "A", "state": "wartet",
           "position": 0, "attempts": 1, "next_try": "2026-09-27T12:01:00", "last_error": "offline",
           "sensitive": False, "history_id": None}
    server.handlers["queue.list"] = lambda s, p: {
        "jobs": [job, dict(job, id=5, position=1, title="B")], "paused": True, "auto_retry": False,
        "next_try": "2026-09-27T12:01:00", "probe": "connect", "waiting_reason": "Drucker offline"}
    server.handlers["queue.cancel"] = lambda s, p: {"ok": True}
    server.handlers["queue.duplicate"] = lambda s, p: {"id": 9}
    backend, _ = daemon_backend(server)
    ops = backend.queue_ops()
    snap = ops.list(include_done=True)
    assert isinstance(snap, QueueSnapshot)
    assert [j.id for j in snap.jobs] == [3, 5]
    assert snap.paused and not snap.auto_retry
    assert snap.next_try == datetime(2026, 9, 27, 12, 1)
    assert snap.waiting_reason == "Drucker offline"
    assert ops.cancel(3) is True
    assert ops.duplicate(3) == 9
    ops.move(5, 0)
    ops.retry()
    ops.retry(3)
    ops.pause()
    ops.resume()
    backend.close()
    assert server.requests == [
        ("queue.list", {"include_done": True}), ("queue.cancel", {"id": 3}), ("queue.duplicate", {"id": 3}),
        ("queue.move", {"id": 5, "position": 0}), ("queue.retry", {"id": None}), ("queue.retry", {"id": 3}),
        ("queue.pause", {}), ("queue.resume", {})]


def test_state_status_listeners_are_decoded(server):
    server.handlers["status"] = lambda s, p: {
        "state": {"state": "verbunden", "transport": "COM4", "last_error": None, "leased": False},
        "status": None, "checked_at": "2026-09-27T12:00:00"}
    backend, _ = daemon_backend(server)
    got = []
    done = threading.Event()
    backend.add_listener("state", got.append)
    backend.add_listener("status", lambda r: (got.append(r), done.set()))
    server.emit("state", {"state": "offline", "transport": None, "last_error": "weg", "leased": False})
    server.emit("status", {"state": {"state": "verbunden"}, "status": None, "checked_at": None})
    assert done.wait(2)
    assert got[0] == StateInfo("offline", None, "weg")
    assert isinstance(got[1], StatusReport)
    report = backend.query_status(quick=True, fresh=False)
    assert server.calls("status") == [{"quick": True, "fresh": False}]
    assert report.checked_at == NOW
    backend.remove_listener("state", got.append)
    backend.close()


# ---------- LocalBackend ----------

def local_backend(transport, hooks=(), history=None):
    warning_relay, cut_relay = Relay(), Relay()
    runner = direct_runner(lambda: PrinterSession(transport, P, lock=contextlib.nullcontext(),
                                                  sleep=lambda s: None))
    pipeline = PrintPipeline(P, runner, history=history, on_warning=warning_relay, on_cut_pause=cut_relay)
    return LocalBackend(pipeline, warning_relay=warning_relay, cut_pause_relay=cut_relay, run_session=runner,
                        post_hooks=hooks, now=lambda: NOW)


def test_local_backend_prints_and_runs_hooks_after_ok():
    hook_calls = []

    def hook(outcome):
        hook_calls.append(outcome.status)
        return ["Archiv: abgelegt"]

    backend = local_backend(MemoryTransport(STATUS_LID_OPEN), hooks=[hook])
    warnings = []
    outcome = backend.execute(make_request(), on_warning=warnings.append)
    assert outcome.status == "ok"
    assert any("Deckel offen" in w for w in warnings)
    assert warnings[-1] == "Archiv: abgelegt"
    assert hook_calls == ["ok"]
    assert backend.kind == "local" and backend.fallback_reason == ""
    assert backend.queue_ops() is None
    assert backend.state_info() == StateInfo("getrennt")

    token = CancelToken()
    token.cancel()
    cancelled = backend.execute(make_request(), cancel=token, on_warning=warnings.append)
    assert cancelled.status == "abgebrochen"
    assert hook_calls == ["ok"]


def test_local_backend_detaches_warning_callback_after_execute():
    backend = local_backend(MemoryTransport(STATUS_LID_OPEN))
    first = []
    backend.execute(make_request(), on_warning=first.append)
    count = len(first)
    backend.execute(make_request(), on_warning=lambda w: None)
    assert len(first) == count


def test_local_backend_query_status():
    backend = local_backend(MemoryTransport(STATUS_OK))
    seen = []
    backend.add_listener("status", seen.append)
    report = backend.query_status(quick=True)
    assert isinstance(report, StatusReport)
    assert report.status.get("lid").value == "zu"
    assert report.checked_at == NOW
    assert seen == [report]
    cached = backend.query_status(fresh=False)
    assert cached.status is report.status
    with backend.lease():
        pass


def test_local_backend_without_cache_has_no_status():
    backend = local_backend(MemoryTransport(STATUS_OK))
    report = backend.query_status(fresh=False)
    assert report.status is None and report.checked_at is None


# ---------- Auswahl ----------

class FakeDaemon:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def _local(reason):
    return ("local", reason)


def test_use_daemon():
    assert use_daemon({}, env={}) is True
    assert use_daemon({}, env={"TAPESMITH_NO_DAEMON": "1"}) is False
    assert use_daemon({"daemon": {"enabled": False}}, env={}) is False


def test_make_backend_decisions():
    def never(**kw):
        raise AssertionError("darf nicht verbinden")

    assert make_backend({}, P, client="cli", local_factory=_local, env={"TAPESMITH_NO_DAEMON": "1"},
                        connector=never) == ("local", "")
    assert make_backend({"daemon": {"enabled": False}}, P, client="cli", local_factory=_local, env={},
                        connector=never) == ("local", "")

    seen = {}

    def ok(**kw):
        seen.update(kw)
        return FakeDaemon()

    backend = make_backend({}, P, client="gui", local_factory=_local, env={}, connector=ok)
    assert isinstance(backend, DaemonBackend) and backend.kind == "daemon"
    assert seen == {"client": "gui", "timeout_s": 2.0}

    def unavailable(**kw):
        raise DaemonUnavailable("keiner da")

    launched = []

    def launcher(cfg, *, client):
        launched.append(client)
        return FakeDaemon()

    backend = make_backend({}, P, client="cli", local_factory=_local, env={}, connector=unavailable,
                           launcher=launcher)
    assert isinstance(backend, DaemonBackend)
    assert launched == ["cli"]

    def failing_launcher(cfg, *, client):
        raise DaemonUnavailable("startet nicht")

    assert make_backend({}, P, client="cli", local_factory=_local, env={}, connector=unavailable,
                        launcher=failing_launcher) == ("local", REASON_UNREACHABLE)
    assert "nicht erreichbar" in REASON_UNREACHABLE

    def other_version(**kw):
        raise ProtocolError("Protokoll 2")

    assert make_backend({}, P, client="cli", local_factory=_local, env={},
                        connector=other_version) == ("local", REASON_OTHER_VERSION)
    assert "andere Version" in REASON_OTHER_VERSION

    launched.clear()
    assert make_backend({}, P, client="cli", local_factory=_local, env={}, connector=unavailable,
                        launcher=launcher, allow_spawn=False) == ("local", REASON_UNREACHABLE)
    assert make_backend({"daemon": {"spawn": False}}, P, client="cli", local_factory=_local, env={},
                        connector=unavailable, launcher=launcher) == ("local", REASON_UNREACHABLE)
    assert launched == []


def test_local_planner_plans_without_printing():
    plan = local_planner({}, P)(make_request())
    assert plan.decision.allowed
