"""Tests für den Warteschlangen-Kern: SQLite-Queue, Persistenz, sensible Aufträge."""

import json
import threading
from datetime import datetime, timedelta

import pytest

from tapesmith.daemon.queue import ACTIVE_STATES, QUEUE_STATES, JobQueue, QueuedJob

NOW = datetime(2026, 9, 27, 12, 0, 0)


def make_clock(t):
    return lambda: t[0]


# 1
def test_add_twice_orders_and_roundtrips(tmp_path):
    t = [NOW]
    with JobQueue(tmp_path / "queue.sqlite3", clock=make_clock(t)) as q:
        id1 = q.add({"a": 1}, source="cli", title="Erster", sensitive=False)
        id2 = q.add({"a": 2}, source="cli", title="Zweiter", sensitive=False)
        jobs = q.list()
        assert [j.id for j in jobs] == [id1, id2]
        assert [j.position for j in jobs] == [0, 1]
        assert all(j.state == "wartet" for j in jobs)
        for j in jobs:
            d = j.to_dict()
            json.dumps(d)  # muss JSON-serialisierbar sein
            back = QueuedJob.from_dict(d)
            assert back == j


# 2
def test_persistence_across_reopen_and_running_reset(tmp_path):
    path = tmp_path / "queue.sqlite3"
    t = [NOW]
    q = JobQueue(path, clock=make_clock(t))
    job_id = q.add({"x": "y"}, source="cli", title="A", sensitive=False)
    q.mark_running(job_id)
    assert q.get(job_id).state == "läuft"
    q.close()

    q2 = JobQueue(path, clock=make_clock(t))
    try:
        job = q2.get(job_id)
        assert job.state == "wartet"  # Dienst war abgestürzt
        assert job.attempts == 1  # attempts bleibt
        assert q2.payload(job_id) == {"x": "y"}
    finally:
        q2.close()


# 3 Sensible Aufträge nie auf Platte
def test_sensitive_payload_never_on_disk(tmp_path):
    path = tmp_path / "queue.sqlite3"
    t = [NOW]
    q = JobQueue(path, clock=make_clock(t))
    job_id = q.add({"secret": "GEHEIM-123"}, source="cli", title="S", sensitive=True)
    assert q.payload(job_id) == {"secret": "GEHEIM-123"}
    q.close()

    data = path.read_bytes()
    wal = path.with_name(path.name + "-wal")
    if wal.exists():
        data += wal.read_bytes()
    assert b"GEHEIM-123" not in data

    q2 = JobQueue(path, clock=make_clock(t))
    try:
        assert q2.payload(job_id) is None
    finally:
        q2.close()


# 4
def test_next_due_respects_next_try_and_pause(tmp_path):
    t = [NOW]
    with JobQueue(tmp_path / "queue.sqlite3", clock=make_clock(t)) as q:
        id1 = q.add({}, source="cli", title="A", sensitive=False)
        q.mark_retry(id1, "offline", NOW + timedelta(seconds=60))
        due = q.next_due(NOW)
        assert due is None  # next_try in der Zukunft

        due = q.next_due(NOW + timedelta(seconds=61))
        assert due is not None
        assert due.id == id1

        q.pause()
        assert q.paused is True
        assert q.next_due(NOW + timedelta(seconds=61)) is None
        q.resume()
        assert q.paused is False
        assert q.next_due(NOW + timedelta(seconds=61)) is not None


def test_pause_state_survives_reopen(tmp_path):
    path = tmp_path / "queue.sqlite3"
    q = JobQueue(path)
    q.pause()
    q.close()
    q2 = JobQueue(path)
    try:
        assert q2.paused is True
    finally:
        q2.close()


# 5
def test_state_sequence_mark_running_retry_done(tmp_path):
    t = [NOW]
    with JobQueue(tmp_path / "queue.sqlite3", clock=make_clock(t)) as q:
        job_id = q.add({"p": 1}, source="cli", title="A", sensitive=False)
        q.mark_running(job_id)
        assert q.get(job_id).attempts == 1
        q.mark_retry(job_id, "offline", NOW + timedelta(seconds=30))
        job = q.get(job_id)
        assert job.state == "wartet"
        assert job.last_error == "offline"
        q.mark_running(job_id)
        assert q.get(job_id).attempts == 2
        q.mark_done(job_id, 17)

        active = q.list()
        assert job_id not in [j.id for j in active]
        done = q.list(include_done=True)
        entry = next(j for j in done if j.id == job_id)
        assert entry.state == "fertig"
        assert entry.history_id == 17
        assert q.payload(job_id) is None


# 6
def test_cancel_duplicate_move_and_unknown_id(tmp_path):
    t = [NOW]
    with JobQueue(tmp_path / "queue.sqlite3", clock=make_clock(t)) as q:
        id1 = q.add({"p": 1}, source="cli", title="Eins", sensitive=False)
        id2 = q.add({"p": 2}, source="cli", title="Zwei", sensitive=False)

        assert q.cancel(id1) is True
        assert q.get(id1).state == "abgebrochen"
        assert q.cancel(id1) is False  # nicht mehr aktiv

        dup_id = q.duplicate(id2)
        dup = q.get(dup_id)
        assert dup.title == "Zwei"
        assert q.payload(dup_id) == {"p": 2}

        ids_before = [j.id for j in q.list()]
        q.move(dup_id, 0)
        jobs = q.list()
        assert jobs[0].id == dup_id
        assert [j.position for j in jobs] == list(range(len(jobs)))

        assert q.cancel(999999) is False  # unbekannt -> nicht aktiv -> False
        with pytest.raises(KeyError):
            q.get(999999)
        with pytest.raises(KeyError):
            q.move(999999, 0)

        # sensibler Auftrag nach Neustart ohne Speicher-payload -> ValueError bei duplicate
        sid = q.add({"secret": "x"}, source="cli", title="Geheim", sensitive=True)
        q.close()
    q2 = JobQueue(tmp_path / "queue.sqlite3", clock=make_clock(t))
    try:
        with pytest.raises(ValueError):
            q2.duplicate(sid)
    finally:
        q2.close()


# 6b
@pytest.mark.parametrize("finish", ["done", "failed", "cancel"])
def test_duplicate_finished_nonsensitive_raises_valueerror(tmp_path, finish):
    t = [NOW]
    with JobQueue(tmp_path / "queue.sqlite3", clock=make_clock(t)) as q:
        job_id = q.add({"p": 1}, source="cli", title="Fertig", sensitive=False)
        q.mark_running(job_id)
        if finish == "done":
            q.mark_done(job_id, 5)
        elif finish == "failed":
            q.mark_failed(job_id, "kaputt")
        else:
            q.cancel(job_id)
        with pytest.raises(ValueError, match="keine gespeicherten Daten"):
            q.duplicate(job_id)


# 7
def test_retry_now_and_earliest_next_try_and_purge(tmp_path):
    t = [NOW]
    with JobQueue(tmp_path / "queue.sqlite3", clock=make_clock(t)) as q:
        id1 = q.add({}, source="cli", title="A", sensitive=False)
        id2 = q.add({}, source="cli", title="B", sensitive=False)
        q.mark_retry(id1, "e", NOW + timedelta(seconds=100))
        q.mark_retry(id2, "e", NOW + timedelta(seconds=50))
        assert q.earliest_next_try() == NOW + timedelta(seconds=50)

        q.retry_now(id1)
        assert q.get(id1).next_try is None
        assert q.get(id2).next_try == NOW + timedelta(seconds=50)

        q.retry_now()  # alle aktiven
        assert q.get(id2).next_try is None

        # purge_done
        q.mark_running(id1)
        q.mark_done(id1, None)
        t[0] = NOW + timedelta(days=10)
        removed = q.purge_done(older_than=timedelta(days=7))
        assert removed == 1
        done = [j for j in q.list(include_done=True) if j.state not in ACTIVE_STATES]
        assert done == []


# 8
def test_thread_safety_concurrent_add(tmp_path):
    t = [NOW]
    with JobQueue(tmp_path / "queue.sqlite3", clock=make_clock(t)) as q:
        def worker():
            for i in range(25):
                q.add({"i": i}, source="cli", title=f"T{i}", sensitive=False)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for th in threads:
            th.start()
        for th in threads:
            th.join(timeout=5)
        jobs = q.list()
        assert len(jobs) == 100
        positions = sorted(j.position for j in jobs)
        assert positions == list(range(100))


def test_queue_states_constants():
    assert QUEUE_STATES == ("wartet", "läuft", "fertig", "fehler", "abgebrochen")
    assert ACTIVE_STATES == ("wartet", "läuft")
