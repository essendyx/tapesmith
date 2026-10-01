"""Druckdienst p12d: PrintService im selben Prozess, ohne Druck."""

import threading

import pytest

from daemon_fakes import (
    PROFILE,
    STATUS_LID_OPEN,
    STATUS_OK,
    ConfigHolder,
    Events,
    FakeClock,
    NullLock,
    TransportFactory,
    close_service,
    make_service,
    request,
    split_jobs,
    wait_until,
)
from tapesmith.connection import ConnectionManager, PrinterOffline
from tapesmith.daemon.service import LEASE_BUSY
from tapesmith.ipc.codec import decode_request
from tapesmith.lock import PrinterBusy
from tapesmith.transport.base import ConnectTimeout, MemoryTransport

INIT = PROFILE.init_packets[0]


@pytest.fixture
def svc(tmp_path):
    made = []

    def build(**kw):
        service, transport = make_service(tmp_path, **kw)
        made.append(service)
        return service, transport

    yield build
    for service in made:
        close_service(service)


def with_events(build, **kw):
    events = Events()
    service, transport = build(emit=events, **kw)
    return service, transport, events


# 0: ConnectionManager.transport_name
def test_manager_transport_name():
    transport = MemoryTransport()
    manager = ConnectionManager(lambda: transport, PROFILE, lock_factory=NullLock, sleep=lambda s: None)
    try:
        assert manager.transport_name is None
        manager.connect()
        assert manager.transport_name == "memory"
        manager.disconnect()
        assert manager.transport_name is None
    finally:
        manager.close()


# 1
def test_submit_ok_with_job_events(svc):
    service, transport, events = with_events(svc)
    outcome = service.submit(request(1), job_key="k1")
    assert outcome.status == "ok"
    assert outcome.history_id is not None
    jobs = split_jobs(transport.written)
    assert len(jobs) == 1
    assert jobs[0][0] == INIT and jobs[0][-1] == PROFILE.feed_command
    phases = [d["phase"] for d in events.of("job")]
    assert phases == ["angenommen", "läuft", "fertig"]
    assert all(d["job_key"] == "k1" for d in events.of("job"))
    assert events.of("job")[-1]["status"] == "ok"
    assert service.state().transport == "memory"


# 2
def test_parallel_submits_never_interleave(svc):
    service, transport = svc()
    results = {}
    start = threading.Barrier(3)

    def worker(source, mark):
        start.wait()
        results[source] = service.submit(request(mark, source=source, rows=300), job_key=source)

    threads = [threading.Thread(target=worker, args=(s, m)) for s, m in (("gui", 1), ("cli", 2), ("hotkey", 3))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert {k: o.status for k, o in results.items()} == {"gui": "ok", "cli": "ok", "hotkey": "ok"}
    jobs = split_jobs(transport.written)
    assert len(jobs) == 3
    for job in jobs:
        assert job[0] == INIT
        assert job[-1] == PROFILE.feed_command
        assert job.count(INIT) == 1
        assert job.count(PROFILE.feed_command) == 1


# 3
def test_confirmation_needed_then_confirmed(svc):
    service, transport = svc(config={"guard": {"confirm_label_mm": 3}})
    first = service.submit(request(1), job_key="a")
    assert first.status == "bestätigung_nötig"
    assert split_jobs(transport.written) == []
    second = service.submit(request(1, confirmed=True), job_key="b")
    assert second.status == "ok"


# 4
def test_offline_enqueue_and_raise(tmp_path, svc):
    factory = TransportFactory(MemoryTransport(STATUS_OK), errors=[ConnectTimeout("weg")] * 5)
    service, _t, events = with_events(svc, transport_factory=factory)
    outcome = service.submit(request(1), job_key="a", enqueue_on_offline=True)
    assert outcome.status == "wartet"
    assert outcome.queue_id is not None
    assert "Warteschlange" in outcome.warnings[0] and f"#{outcome.queue_id}" in outcome.warnings[0]
    jobs = service.queue.list()
    assert [j.id for j in jobs] == [outcome.queue_id]
    payload = service.queue.payload(outcome.queue_id)
    assert payload["request"]["confirmed"] is True
    assert decode_request(payload["request"]).meta.title == "T"
    assert events.of("queue")

    with pytest.raises(ConnectTimeout):   # PrinterOffline ist eine ConnectTimeout
        service.submit(request(2), job_key="b")
    assert len(service.queue.list()) == 1


def test_offline_queue_disabled_raises(svc):
    factory = TransportFactory(MemoryTransport(STATUS_OK), errors=[ConnectTimeout("weg")])
    service, _t = svc(transport_factory=factory, config={"queue": {"enabled": False}})
    with pytest.raises(ConnectTimeout):
        service.submit(request(1), job_key="a", enqueue_on_offline=True)
    assert service.queue.list() == []


def test_offline_raises_printer_offline_in_backoff(svc):
    factory = TransportFactory(MemoryTransport(STATUS_OK), errors=[ConnectTimeout("weg")])
    service, _t = svc(transport_factory=factory)
    with pytest.raises(ConnectTimeout):
        service.submit(request(1), job_key="a")
    with pytest.raises(PrinterOffline):
        service.submit(request(2), job_key="b")
    assert service.queue.list() == []


# 5
def test_sensitive_offline_not_on_disk(tmp_path, svc):
    factory = TransportFactory(MemoryTransport(STATUS_OK), errors=[ConnectTimeout("weg")])
    service, _t = svc(transport_factory=factory)
    req = request(1, sensitive=True, values={"pin": "GEHEIM-4711"})
    outcome = service.submit(req, job_key="a", enqueue_on_offline=True)
    assert outcome.status == "wartet"
    assert service.queue.payload(outcome.queue_id) is not None
    service.queue._conn.execute("PRAGMA wal_checkpoint(FULL)")
    data = b"".join(p.read_bytes() for p in tmp_path.glob("q.db*"))
    assert b"GEHEIM-4711" not in data
    assert b"head_png" not in data


# 6
def test_cancel_waiting_job(svc):
    gate = threading.Event()
    entered = threading.Event()

    class Blocking(MemoryTransport):
        def write(self, data):
            if data == INIT and not gate.is_set():
                entered.set()
                gate.wait(5)
            super().write(data)

    service, transport = svc(transport=Blocking(STATUS_OK))
    results = {}
    a = threading.Thread(target=lambda: results.setdefault("a", service.submit(request(1), job_key="a")))
    a.start()
    assert entered.wait(5)
    b = threading.Thread(target=lambda: results.setdefault("b", service.submit(request(2), job_key="b")))
    b.start()
    assert wait_until(lambda: "b" in service._tokens)
    assert service.cancel("b") is True
    b.join(5)
    assert results["b"].status == "abgebrochen"
    gate.set()
    a.join(5)
    assert results["a"].status == "ok"
    assert len(split_jobs(transport.written)) == 1
    assert service.cancel("gibt-es-nicht") is False


# 7
def test_progress_and_preflight_warning(svc):
    service, _t, events = with_events(svc, responses=STATUS_LID_OPEN)
    outcome = service.submit(request(1, rows=600), job_key="p")
    assert outcome.status == "ok"
    progress = events.of("progress")
    assert progress and all(p["job_key"] == "p" for p in progress)
    assert progress[-1]["done"] == progress[-1]["total"] == 600
    warnings = [w for w in events.of("warning") if "Deckel" in w["text"]]
    assert warnings and warnings[0]["job_key"] == "p"


# 8
def test_cut_pause_continue(svc):
    service, transport, events = with_events(svc, config={"cut_pause_s": 0})
    result = {}
    t = threading.Thread(target=lambda: result.setdefault("o", service.submit(request(1, copies=2), job_key="c")))
    t.start()
    assert wait_until(lambda: any(d["state"] == "start" for d in events.of("cut_pause")))
    start = [d for d in events.of("cut_pause") if d["state"] == "start"][0]
    assert start["job_key"] == "c" and start["done"] == 1 and start["total"] == 2
    assert service.continue_cut() is True
    t.join(5)
    assert result["o"].status == "ok"
    assert len(split_jobs(transport.written)) == 2


# 9
def test_status_fresh_and_cached(svc):
    service, transport, events = with_events(svc)
    report = service.status(fresh=True)
    assert report.status.get("battery").value == 0x4b
    assert report.status.get("lid").value == "zu"
    assert report.checked_at is not None
    assert events.of("status")
    written = len(transport.written)
    cached = service.status(fresh=False)
    assert cached.status.get("lid").value == "zu"
    assert len(transport.written) == written


def test_status_without_cache(svc):
    service, _t = svc()
    report = service.status(fresh=False)
    assert report.status is None and report.checked_at is None


# 10
def test_lease(svc):
    clock = FakeClock()
    service, transport, events = with_events(svc, clock=clock)
    service.preconnect()
    assert wait_until(lambda: service.state().state == "verbunden")
    owner = object()
    lease_id = service.lease(owner, timeout_s=60)
    assert lease_id
    assert transport.closed
    assert service.state().leased is True
    assert events.of("state")[-1]["leased"] is True
    with pytest.raises(PrinterBusy, match=LEASE_BUSY):
        service.submit(request(1), job_key="x")
    queued = service.submit(request(1), job_key="y", enqueue_on_offline=True)
    assert queued.status == "wartet"
    with pytest.raises(PrinterBusy):
        service.lease(object())
    with pytest.raises(PrinterBusy):
        service.status(fresh=True)
    service.preconnect()   # während Lease: nichts
    service.release_owner(object())       # fremder Besitzer: bleibt reserviert
    assert service.leased
    service.release_owner(owner)
    assert not service.leased
    assert events.of("state")[-1]["leased"] is False

    service.lease(owner, timeout_s=10)
    assert service.leased
    clock.now += 11
    service.housekeeping()
    assert not service.leased
    assert service.submit(request(2), job_key="z").status == "ok"


def test_release_by_id(svc):
    service, _t = svc()
    lease_id = service.lease("me")
    service.release("falsch")
    assert service.leased
    service.release(lease_id)
    assert not service.leased


# 11
def test_reload_policy_transport_and_broken_config(svc):
    holder = ConfigHolder()
    factory = TransportFactory(MemoryTransport(STATUS_OK))
    service, _t, events = with_events(svc, config_loader=holder, transport_factory=factory)
    assert service.submit(request(1), job_key="a").status == "ok"
    assert factory.built == 1

    holder.cfg["guard"] = {"confirm_label_mm": 3}
    service.reload()
    assert service.submit(request(2), job_key="b").status == "bestätigung_nötig"
    assert factory.built == 1

    holder.cfg["transport"] = "COM9"
    service.reload()
    assert factory.built == 2
    assert service.config["transport"] == "COM9"

    holder.error = ValueError("kaputt")
    service.reload()
    texts = [w["text"] for w in events.of("warning")]
    assert any("Konfiguration fehlerhaft" in t and "kaputt" in t for t in texts)
    assert service.config["transport"] == "COM9"
    assert service.submit(request(3, confirmed=True), job_key="c").status == "ok"


def test_reload_on_file_change(tmp_path, app_home, svc):
    holder = ConfigHolder()
    service, _t = svc(config_loader=holder, watch_files=True)
    (app_home / "config.json").write_text("{}", encoding="utf-8")
    holder.cfg["guard"] = {"confirm_label_mm": 3}
    assert service.submit(request(1), job_key="a").status == "bestätigung_nötig"


# 12
def test_archive_hook(svc):
    calls = []

    def hook(outcome):
        calls.append(outcome)
        return ["Archiv: gespeichert"]

    service, _t, events = with_events(svc, archive_factory=lambda cfg: hook)
    outcome = service.submit(request(1), job_key="a")
    assert outcome.status == "ok"
    assert calls == [outcome]
    assert any(w["text"] == "Archiv: gespeichert" and w["job_key"] == "a" for w in events.of("warning"))

    def broken(outcome):
        raise RuntimeError("Platte voll")

    service2, _t2 = svc(archive_factory=lambda cfg: broken)
    assert service2.submit(request(2), job_key="b").status == "ok"


# Leerlauf und Haushalt
def test_idle_since_and_housekeeping(svc):
    clock = FakeClock(50.0)
    service, _t = svc(clock=clock)
    assert service.idle_since() == 50.0
    clock.now = 60.0
    service.submit(request(1), job_key="a")
    assert service.idle_since() is None           # Manager noch verbunden
    service.disconnect()
    assert service.idle_since() == 60.0
    service.lease("x")
    assert service.idle_since() is None
    service.release_owner("x")
    service.housekeeping()
    service.housekeeping()     # zweimal am selben Tag: kein Fehler


def test_queue_operations_emit_events(svc):
    factory = TransportFactory(MemoryTransport(STATUS_OK), errors=[ConnectTimeout("weg")])
    service, _t, events = with_events(svc, transport_factory=factory)
    q1 = service.submit(request(1), job_key="a", enqueue_on_offline=True).queue_id
    q2 = service.queue_duplicate(q1)
    service.queue_move(q2, 0)
    assert [j.id for j in service.queue.list()] == [q2, q1]
    service.queue_pause()
    snap = service.queue_snapshot()
    assert snap["paused"] is True and len(snap["jobs"]) == 2
    assert set(snap) == {"jobs", "paused", "auto_retry", "next_try", "probe", "waiting_reason"}
    service.queue_resume()
    service.queue_retry(None)
    assert service.queue_cancel(q1) is True
    assert len(service.queue_snapshot(include_done=True)["jobs"]) == 2
    assert len(events.of("queue")) >= 6


def test_erneut_verbinden_umgeht_backoff_mit_laengerer_wartezeit(svc):
    seen: list[float] = []
    inner = TransportFactory(MemoryTransport(STATUS_OK), errors=[ConnectTimeout("weg")])

    def factory(cfg, profile):
        seen.append(float(cfg["connect_timeout_s"]))
        return inner(cfg, profile)

    service, _t = svc(transport_factory=factory)
    with pytest.raises(ConnectTimeout):
        service.status()
    with pytest.raises(PrinterOffline):
        service.status()                      # Backoff: sofort offline
    report = service.status(reconnect=True)   # „Erneut verbinden“: eigener Aufbau, 15 s
    assert report.status is not None and report.checked_at is not None
    assert seen[-1] == 15.0
