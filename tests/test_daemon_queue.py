"""Tests für den Warteschlangen-Kern: SQLite-Queue, Persistenz, sensible Aufträge."""

import json
import sqlite3
import threading
import time
from datetime import datetime, timedelta

import pytest

from tapesmith.daemon.queue import ACTIVE_STATES, QUEUE_STATES, JobQueue, QueueClosed, QueuedJob

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


class SlowCommits:
    """Verbindung mit langsamem `commit()` wie auf einem CI-Rechner mit trägem Datenträger.

    `before_commit` läuft vor jedem Commit (Verzögerung oder Anhalten an einem Event)."""

    def __init__(self, conn, before_commit):
        self._conn = conn
        self._before_commit = before_commit

    def commit(self):
        self._before_commit()
        self._conn.commit()

    def __getattr__(self, name):
        return getattr(self._conn, name)


def _run_threads(target, count, *, deadline_s=120.0):
    """Startet `count` Threads, wartet auf alle und meldet Ausnahmen aus den Threads als Liste.
    Ein Thread, der nach `deadline_s` noch läuft, lässt den Test scheitern (statt still weiterzulaufen
    und später auf eine geschlossene Warteschlange zu treffen)."""
    errors = []

    def guarded():
        try:
            target()
        except BaseException as exc:  # noqa: BLE001 (im Test sichtbar machen)
            errors.append(exc)

    threads = [threading.Thread(target=guarded, daemon=True) for _ in range(count)]
    for th in threads:
        th.start()
    end = time.monotonic() + deadline_s
    for th in threads:
        th.join(max(0.0, end - time.monotonic()))
    assert not any(th.is_alive() for th in threads), f"Threads nach {deadline_s} s nicht fertig"
    return errors


# 8
def test_thread_safety_concurrent_add(tmp_path):
    """Viele Threads, verzögerte Commits: kein Auftrag geht verloren, Positionen lückenlos.

    Die Verzögerung je Commit hält die Sperre länger und lässt die Threads sicher gegeneinander
    laufen. Auf dem CI-Rechner dauerte ein Commit bis zu 0,2 s; deshalb wenige Einfügungen je
    Thread und eine großzügige Frist statt einer knappen festen Wartezeit."""
    t = [NOW]
    with JobQueue(tmp_path / "queue.sqlite3", clock=make_clock(t)) as q:
        q._conn = SlowCommits(q._conn, lambda: time.sleep(0.002))

        def worker():
            for i in range(8):
                q.add({"i": i}, source="cli", title=f"T{i}", sensitive=False)

        errors = _run_threads(worker, 8)
        assert errors == []
        jobs = q.list()
        assert len(jobs) == 64
        assert len({j.id for j in jobs}) == 64
        assert sorted(j.position for j in jobs) == list(range(64))


def test_close_waits_for_running_access_then_rejects_clearly(tmp_path):
    """`close()` wartet auf einen laufenden Zugriff; danach meldet jeder Zugriff `QueueClosed`
    statt eines rohen `sqlite3.ProgrammingError` aus der geschlossenen Verbindung."""
    q = JobQueue(tmp_path / "queue.sqlite3")
    entered, release = threading.Event(), threading.Event()

    def hold_commit():
        entered.set()
        assert release.wait(30)

    q._conn = SlowCommits(q._conn, hold_commit)
    results = []
    adder = threading.Thread(target=lambda: results.append(
        q.add({"i": 1}, source="cli", title="T", sensitive=False)), daemon=True)
    adder.start()
    assert entered.wait(30)
    closer = threading.Thread(target=q.close, daemon=True)
    closer.start()
    closer.join(0.2)
    assert closer.is_alive()          # wartet, bis das laufende add() fertig ist
    release.set()
    adder.join(30)
    closer.join(30)
    assert not adder.is_alive() and not closer.is_alive()
    assert results == [1]
    assert q.closed
    with pytest.raises(QueueClosed):
        q.add({"i": 2}, source="cli", title="T", sensitive=False)
    with pytest.raises(QueueClosed):
        q.list()
    with pytest.raises(QueueClosed):
        _ = q.paused
    q.close()                         # mehrfaches Schließen ist harmlos
    # Die Einfügung vor dem Schließen ist dauerhaft gespeichert.
    with JobQueue(tmp_path / "queue.sqlite3") as again:
        assert [j.id for j in again.list()] == [1]


def test_failed_commit_rolls_back_instead_of_riding_along(tmp_path):
    """Scheitert der Commit (Datei gesperrt, Datenträger voll), bleibt vom gescheiterten `add()`
    nichts übrig: weder in der Datenbank (der nächste Commit schriebe es sonst mit fest) noch im
    Speicher für sensible Inhalte."""
    q = JobQueue(tmp_path / "queue.sqlite3")
    failures = [sqlite3.OperationalError("database is locked")]

    def maybe_fail():
        if failures:
            raise failures.pop()

    q._conn = SlowCommits(q._conn, maybe_fail)
    try:
        with pytest.raises(sqlite3.OperationalError):
            q.add({"secret": 1}, source="cli", title="gescheitert", sensitive=True)
        second = q.add({"i": 2}, source="cli", title="zweiter", sensitive=False)
        jobs = q.list()
        assert [(j.id, j.title, j.position) for j in jobs] == [(second, "zweiter", 0)]
        assert q._memory == {}
    finally:
        q.close()
    with JobQueue(tmp_path / "queue.sqlite3") as again:
        assert [j.title for j in again.list()] == ["zweiter"]


def test_queue_states_constants():
    assert QUEUE_STATES == ("wartet", "läuft", "fertig", "fehler", "abgebrochen")
    assert ACTIVE_STATES == ("wartet", "läuft")
