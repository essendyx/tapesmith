"""Warteschlangen-Läufer: Backoff, Probe, Deckel, Lease, Fehler der Deckelprüfung, Duplikat."""

from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from daemon_fakes import (
    STATUS_LID_OPEN,
    STATUS_OK,
    FakeClock,
    FakeNow,
    TransportFactory,
    close_service,
    make_service,
    request,
    split_jobs,
    wait_until,
)
from tapesmith.connection import PrinterOffline
from tapesmith.daemon.probe import Backoff, NullProbe, RetryScheduler
from tapesmith.daemon.queue import JobQueue
from tapesmith.daemon.runner import REASON_SENSITIVE_LOST, QueueRunner
from tapesmith.ipc.codec import encode_request
from tapesmith.lock import PrinterBusy
from tapesmith.pipeline import DOUBLE_PRESS_REASON
from tapesmith.transport.base import ConnectTimeout, MemoryTransport

T0 = datetime(2026, 9, 27, 12, 0, 0)


class CountingProbe:
    name = "test"

    def __init__(self, result=True):
        self.result = result
        self.calls = 0

    def check(self):
        self.calls += 1
        return self.result


class Env:
    """Dienst + Läufer mit gemeinsamer Fake-Zeit (datetime für die Queue, monotonic für den Scheduler)."""

    def __init__(self, tmp_path, *, probe=None, auto_retry=True, service_wrapper=None, attach=True, **kw):
        self.now = FakeNow(T0)
        self.mono = FakeClock(1000.0)
        self.service, self.transport = make_service(tmp_path, **kw)
        self.scheduler = RetryScheduler(Backoff(30, 300), auto_retry=auto_retry, clock=self.mono)
        self.probe = probe or CountingProbe(True)
        target = service_wrapper(self.service) if service_wrapper else self.service
        self.runner = QueueRunner(target, self.service.queue, self.scheduler, self.probe, now=self.now)
        if attach:
            self.service.attach_runner(self.runner)

    def advance(self, seconds):
        self.now.now += timedelta(seconds=seconds)
        self.mono.now += seconds

    def add(self, mark=1, sensitive=False, **kw):
        req = replace(request(mark, sensitive=sensitive, **kw), confirmed=True)
        return self.service.queue.add({"request": encode_request(req)}, source=req.meta.source,
                                      title=req.meta.title, sensitive=sensitive)

    def job(self, job_id):
        return self.service.queue.get(job_id)

    def close(self):
        close_service(self.service)


@pytest.fixture
def env(tmp_path):
    made = []

    def build(**kw):
        e = Env(tmp_path / f"e{len(made)}", **kw)
        made.append(e)
        return e

    for i in range(4):
        (tmp_path / f"e{i}").mkdir()
    yield build
    for e in made:
        e.close()


# 13
def test_no_jobs_waits(env):
    e = env()
    decision = e.runner.tick()
    assert decision.action == "warten"
    assert e.probe.calls == 0


# 14
def test_due_job_is_printed(env):
    e = env()
    job_id = e.add()
    decision = e.runner.tick()
    assert decision.action == "drucken"
    assert "1 Aufträge gedruckt" in decision.reason
    job = e.job(job_id)
    assert job.state == "fertig"
    assert job.history_id is not None
    assert len(split_jobs(e.transport.written)) == 1


# 15
def test_offline_on_reprint_backoff(env):
    factory = TransportFactory(MemoryTransport(STATUS_OK),
                               errors=[None, ConnectTimeout("weg"), None, ConnectTimeout("weg")])
    e = env(transport_factory=factory, config={"idle_timeout_s": 0})
    job_id = e.add()
    assert e.runner.tick().action == "warten"
    job = e.job(job_id)
    assert job.state == "wartet"
    assert job.last_error == "Drucker nicht erreichbar"
    assert job.next_try == T0 + timedelta(seconds=30)
    assert e.probe.calls == 1

    e.advance(10)
    assert e.runner.tick().action == "warten"
    assert e.probe.calls == 1            # vor Ablauf: keine Probe

    e.advance(20)
    e.runner.tick()
    assert e.probe.calls == 2
    assert e.job(job_id).next_try == e.now.now + timedelta(seconds=60)
    assert e.job(job_id).attempts == 2


class StatusFails:
    """Attrappe um den echten Dienst: `status(quick=True)` wirft, `submit` wird gezählt."""

    def __init__(self, service, error):
        self._service = service
        self.error = error
        self.submits = 0

    def status(self, *, quick=False, **kw):
        if self.error is not None:
            raise self.error
        return self._service.status(quick=quick, **kw)

    def submit(self, *args, **kw):
        self.submits += 1
        return self._service.submit(*args, **kw)

    def __getattr__(self, name):
        return getattr(self._service, name)


@pytest.mark.parametrize("error", [ConnectTimeout("weg"), PrinterOffline("offline")])
def test_lid_check_offline(env, error):
    holder = {}

    def wrap(service):
        holder["w"] = StatusFails(service, error)
        return holder["w"]

    e = env(service_wrapper=wrap)
    wrapper = holder["w"]
    job_id = e.add()
    assert e.runner.tick().action == "warten"
    job = e.job(job_id)
    assert job.state == "wartet"
    assert job.last_error == "Drucker nicht erreichbar"
    assert job.next_try == T0 + timedelta(seconds=30)
    assert job.attempts == 0
    assert wrapper.submits == 0

    e.advance(30)
    e.runner.tick()
    assert e.job(job_id).next_try == e.now.now + timedelta(seconds=60)
    assert wrapper.submits == 0


def test_lid_check_busy_does_not_count_offline(env):
    holder = {}

    def wrap(service):
        holder["w"] = StatusFails(service, PrinterBusy("reserviert"))
        return holder["w"]

    e = env(service_wrapper=wrap)
    wrapper = holder["w"]
    job_id = e.add()
    e.runner.tick()
    job = e.job(job_id)
    assert job.state == "wartet"
    assert "reserviert/belegt" in job.last_error
    assert job.next_try == T0 + timedelta(seconds=30)
    assert job.attempts == 0
    assert wrapper.submits == 0

    wrapper.error = ConnectTimeout("weg")
    e.advance(30)
    e.runner.tick()
    assert e.job(job_id).next_try == e.now.now + timedelta(seconds=30)   # nicht 60


def test_lid_check_other_error_still_prints(env):
    holder = {}

    def wrap(service):
        holder["w"] = StatusFails(service, RuntimeError("Status kaputt"))
        return holder["w"]

    e = env(service_wrapper=wrap)
    job_id = e.add()
    assert e.runner.tick().action == "drucken"
    assert e.job(job_id).state == "fertig"
    assert holder["w"].submits == 1


# 16
def test_probe_false_no_connect(env):
    factory = TransportFactory(MemoryTransport(STATUS_OK))
    probe = CountingProbe(False)
    e = env(probe=probe, transport_factory=factory)
    job_id = e.add()
    decision = e.runner.tick()
    assert decision.action == "warten"
    assert decision.wait_s == 30
    assert factory.calls == 0
    assert e.job(job_id).next_try == T0 + timedelta(seconds=30)

    e.advance(30)
    e.runner.tick()
    assert e.job(job_id).next_try == e.now.now + timedelta(seconds=60)   # verlängert
    assert factory.calls == 0

    probe.result = True
    e.advance(60)
    assert e.runner.tick().action == "drucken"
    assert e.job(job_id).state == "fertig"


def test_null_probe_prints(env):
    e = env(probe=NullProbe())
    job_id = e.add()
    assert e.runner.tick().action == "drucken"
    assert e.job(job_id).state == "fertig"


# 17
def test_lid_open_pauses(env):
    e = env(responses=STATUS_LID_OPEN)
    job_id = e.add()
    e.runner.tick()
    job = e.job(job_id)
    assert job.state == "wartet"
    assert "Deckel offen" in job.last_error
    assert split_jobs(e.transport.written) == []


def test_auto_retry_off_only_manual(env):
    e = env(auto_retry=False)
    job_id = e.add()
    decision = e.runner.tick()
    assert decision.action == "warten"
    assert e.probe.calls == 0
    assert e.job(job_id).state == "wartet"
    e.runner.wake(manual=True)
    assert e.runner.tick().action == "drucken"
    assert e.job(job_id).state == "fertig"


# 18
def test_sensitive_without_payload_after_restart(env, tmp_path):
    e = env()
    job_id = e.add(sensitive=True)
    path = e.service.queue.path
    fresh = JobQueue(path)
    try:
        runner = QueueRunner(e.service, fresh, e.scheduler, e.probe, now=e.now)
        runner.tick()
        job = fresh.get(job_id)
        assert job.state == "fehler"
        assert job.last_error == REASON_SENSITIVE_LOST
    finally:
        fresh.close()


def test_lease_waits(env):
    e = env()
    e.add()
    e.service.lease("diagnose")
    decision = e.runner.tick()
    assert decision.action == "warten"
    assert "reserviert" in decision.reason
    assert e.probe.calls == 0


def test_paused_waits(env):
    e = env()
    e.add()
    e.service.queue_pause()
    assert e.runner.tick().action == "warten"
    assert e.runner.last_reason == "Warteschlange pausiert"


# 18a
def test_duplicate_prints_both_with_real_debouncer(env):
    clock = FakeClock(500.0)   # steht still: "kurz nacheinander"
    factory = TransportFactory(MemoryTransport(STATUS_OK), errors=[ConnectTimeout("weg")])
    e = env(transport_factory=factory, debounce_s=1.5, clock=clock)
    req = request(7, source="hotkey")
    first = e.service.submit(req, job_key="a", enqueue_on_offline=True)
    assert first.status == "wartet" and first.queue_id == 1
    dup = e.service.queue_duplicate(1)
    assert dup == 2
    e.advance(30)
    decision = e.runner.tick()
    assert decision.action == "drucken"
    jobs = {j.id: j for j in e.service.queue.list(include_done=True)}
    assert jobs[1].state == "fertig" and jobs[2].state == "fertig"
    assert jobs[1].history_id and jobs[2].history_id and jobs[1].history_id != jobs[2].history_id
    assert DOUBLE_PRESS_REASON not in (jobs[1].last_error + jobs[2].last_error)
    assert len(split_jobs(factory.transport.written)) == 2

    req2 = request(8, source="hotkey")
    assert e.service.submit(req2, job_key="b").status == "ok"
    second = e.service.submit(req2, job_key="c")
    assert second.status == "abgelehnt"
    assert DOUBLE_PRESS_REASON in second.reasons


# Thread-Betrieb
def test_thread_start_wake_stop(env):
    e = env()
    e.runner.start()
    try:
        job_id = e.add()
        e.runner.wake()
        assert wait_until(lambda: e.job(job_id).state == "fertig")
    finally:
        e.runner.stop()
    assert e.runner.next_try() is None


def test_notify_offline_sets_next_try(env):
    e = env()
    job_id = e.add()
    e.runner.notify_offline()
    assert e.job(job_id).next_try == T0 + timedelta(seconds=30)
    assert e.runner.next_try() == T0 + timedelta(seconds=30)
    snap = e.service.queue_snapshot()
    assert snap["next_try"] == (T0 + timedelta(seconds=30)).isoformat(timespec="seconds")
    assert snap["probe"] == "test"


# ---------- Einstellungen wirken ohne Dienst-Neustart (reload -> Läufer) ----------

def _set_queue(holder, **values):
    holder.cfg["queue"] = {**holder.cfg.get("queue", {}), **values}


def test_reload_auto_retry_off_stops_runner_until_manual(env):
    from daemon_fakes import ConfigHolder

    holder = ConfigHolder()
    e = env(config_loader=holder)
    job_id = e.add()
    _set_queue(holder, auto_retry=False)
    e.service.reload()
    decision = e.runner.tick()
    assert decision.action == "warten"
    assert decision.reason == RetryScheduler.AUTO_OFF_REASON
    assert e.probe.calls == 0
    assert e.job(job_id).state == "wartet"
    assert split_jobs(e.transport.written) == []
    assert e.service.queue_snapshot()["auto_retry"] is False

    e.runner.wake(manual=True)                 # Nachdrucken von Hand geht weiterhin
    assert e.runner.tick().action == "drucken"
    assert e.job(job_id).state == "fertig"

    job2 = e.add(2)
    assert e.runner.tick().action == "warten"
    _set_queue(holder, auto_retry=True)
    e.service.reload()
    assert e.runner.tick().action == "drucken"
    assert e.job(job2).state == "fertig"


def test_reload_backoff_and_probe(env):
    from daemon_fakes import ConfigHolder

    holder = ConfigHolder()
    factory = TransportFactory(MemoryTransport(STATUS_OK), errors=[None, ConnectTimeout("weg")])
    e = env(config_loader=holder, transport_factory=factory, config={"idle_timeout_s": 0})
    holder.cfg["idle_timeout_s"] = 0
    assert e.runner.probe_name == "test"
    _set_queue(holder, backoff_start_s=5, backoff_max_s=10, probe="off")
    e.service.reload()
    assert e.runner.probe_name == "none"
    job_id = e.add()
    assert e.runner.tick().action == "warten"
    assert e.job(job_id).next_try == T0 + timedelta(seconds=5)


def test_reload_with_broken_backoff_keeps_runner(env, caplog):
    from daemon_fakes import ConfigHolder

    holder = ConfigHolder()
    e = env(config_loader=holder)
    _set_queue(holder, backoff_start_s=50, backoff_max_s=10)
    e.service.reload()
    assert "Warteschlangen-Einstellungen" in caplog.text
    e.add()
    assert e.runner.tick().action == "drucken"      # alte Einstellungen bleiben aktiv


def test_default_runner_follows_reload(tmp_path):
    from daemon_fakes import ConfigHolder
    from tapesmith.daemon.instance import default_runner

    holder = ConfigHolder({"queue": {"probe": "off"}})
    service, _t = make_service(tmp_path, config_loader=holder)
    try:
        runner = default_runner(service)
        service.attach_runner(runner)
        assert runner.auto_retry is True
        _set_queue(holder, auto_retry=False)
        service.reload()
        assert runner.auto_retry is False
    finally:
        close_service(service)
