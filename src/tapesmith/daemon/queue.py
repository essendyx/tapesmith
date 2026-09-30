"""Persistente Druckwarteschlange: SQLite, Zustände, Reihenfolge, Nachdruck-Metadaten.

Aufträge überstehen einen Neustart des Dienstes. Sensible Aufträge landen nie mit
Inhalt auf der Platte: ihr `payload` lebt nur im Prozessspeicher und ist nach einem
Neustart nicht mehr da (`payload()` liefert dann `None`).
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from tapesmith import paths
from tapesmith.i18n import _t

QUEUE_STATES = ("wartet", "läuft", "fertig", "fehler", "abgebrochen")
ACTIVE_STATES = ("wartet", "läuft")
DONE_STATES = ("fertig", "fehler", "abgebrochen")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS jobs(
    id INTEGER PRIMARY KEY,
    created TEXT NOT NULL,
    source TEXT NOT NULL,
    title TEXT NOT NULL,
    state TEXT NOT NULL,
    position INTEGER NOT NULL,
    attempts INTEGER NOT NULL,
    next_try TEXT,
    last_error TEXT NOT NULL,
    sensitive INTEGER NOT NULL,
    history_id INTEGER,
    payload_json TEXT
);
"""
META_SQL = """
CREATE TABLE IF NOT EXISTS meta(
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat(timespec="seconds") if dt is not None else None


def _from_iso(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text) if text is not None else None


@dataclass(frozen=True)
class QueuedJob:
    id: int
    created: datetime
    source: str
    title: str
    state: str
    position: int
    attempts: int
    next_try: datetime | None
    last_error: str
    sensitive: bool
    history_id: int | None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "created": self.created.isoformat(timespec="seconds"),
            "source": self.source,
            "title": self.title,
            "state": self.state,
            "position": self.position,
            "attempts": self.attempts,
            "next_try": _iso(self.next_try),
            "last_error": self.last_error,
            "sensitive": self.sensitive,
            "history_id": self.history_id,
        }

    @staticmethod
    def from_dict(data: dict) -> "QueuedJob":
        return QueuedJob(
            id=data["id"],
            created=datetime.fromisoformat(data["created"]),
            source=data["source"],
            title=data["title"],
            state=data["state"],
            position=data["position"],
            attempts=data["attempts"],
            next_try=_from_iso(data["next_try"]),
            last_error=data["last_error"],
            sensitive=data["sensitive"],
            history_id=data["history_id"],
        )


class QueueClosed(RuntimeError):
    """Die Warteschlange wurde geschlossen (Dienst fährt herunter); kein Zugriff mehr möglich."""


class JobQueue:
    """Eine SQLite-Verbindung für alle Threads, jeder Zugriff unter `_lock`.

    `close()` wartet auf einen laufenden Zugriff und schließt dann; spätere Aufrufe werfen
    `QueueClosed` statt eines rohen `sqlite3.ProgrammingError` aus einer geschlossenen Verbindung.
    """

    def __init__(self, path: Path | None = None, *, clock: Callable[[], datetime] = datetime.now):
        self.path = Path(path) if path is not None else (paths.app_dir() / "queue.sqlite3")
        self._clock = clock
        self._lock = threading.Lock()
        self._closed = False
        self._memory: dict[int, dict] = {}
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.execute(SCHEMA_SQL)
            self._conn.execute(META_SQL)
            # Dienst war abgestürzt: "läuft" -> "wartet", attempts bleibt.
            self._conn.execute("UPDATE jobs SET state='wartet' WHERE state='läuft'")
            self._conn.commit()

    # ---------- interne Hilfen ----------

    @contextmanager
    def _open(self) -> Iterator[None]:
        """Sperre halten und sicherstellen, dass die Verbindung noch offen ist.

        Scheitert ein Zugriff mittendrin (etwa `commit()` bei vollem Datenträger oder gesperrter
        Datei), wird die offene Transaktion zurückgerollt. Sonst bliebe sie hängen und der nächste
        erfolgreiche Zugriff schriebe die halbe Änderung mit fest (ein Auftrag, dessen `add()` mit
        Fehler endete, stünde dann doch in der Warteschlange)."""
        with self._lock:
            if self._closed:
                raise QueueClosed(_t("Warteschlange ist geschlossen"))
            try:
                yield
            except BaseException:
                if self._conn.in_transaction:
                    self._conn.rollback()
                raise

    def _row_to_job(self, row: sqlite3.Row) -> QueuedJob:
        return QueuedJob(
            id=row["id"],
            created=datetime.fromisoformat(row["created"]),
            source=row["source"],
            title=row["title"],
            state=row["state"],
            position=row["position"],
            attempts=row["attempts"],
            next_try=_from_iso(row["next_try"]),
            last_error=row["last_error"],
            sensitive=bool(row["sensitive"]),
            history_id=row["history_id"],
        )

    def _get_row(self, job_id: int) -> sqlite3.Row:
        row = self._conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(_t("Warteschlangen-Auftrag {job_id} gibt es nicht", job_id=job_id))
        return row

    def _next_position_locked(self) -> int:
        row = self._conn.execute(
            "SELECT COALESCE(MAX(position), -1) FROM jobs WHERE state IN (?,?)", ACTIVE_STATES
        ).fetchone()
        return row[0] + 1

    def _renumber_active_locked(self) -> None:
        rows = self._conn.execute(
            "SELECT id FROM jobs WHERE state IN (?,?) ORDER BY position", ACTIVE_STATES
        ).fetchall()
        for pos, row in enumerate(rows):
            self._conn.execute("UPDATE jobs SET position=? WHERE id=?", (pos, row["id"]))

    # ---------- öffentliche API ----------

    def add(self, payload: dict, *, source: str, title: str, sensitive: bool) -> int:
        created = self._clock()
        with self._open():
            position = self._next_position_locked()
            payload_json = None if sensitive else json.dumps(payload, ensure_ascii=False)
            cur = self._conn.execute(
                "INSERT INTO jobs(created, source, title, state, position, attempts, next_try, "
                "last_error, sensitive, history_id, payload_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (created.isoformat(timespec="seconds"), source, title, "wartet", position, 0,
                 None, "", int(sensitive), None, payload_json),
            )
            job_id = cur.lastrowid
            self._conn.commit()
            if sensitive:
                self._memory[job_id] = payload
            return job_id

    def get(self, job_id: int) -> QueuedJob:
        with self._open():
            return self._row_to_job(self._get_row(job_id))

    def payload(self, job_id: int) -> dict | None:
        with self._open():
            row = self._get_row(job_id)
            if row["sensitive"]:
                return self._memory.get(job_id)
            if row["payload_json"] is None:
                return None
            return json.loads(row["payload_json"])

    def list(self, include_done: bool = False) -> list[QueuedJob]:
        with self._open():
            rows = self._conn.execute(
                "SELECT * FROM jobs WHERE state IN (?,?) ORDER BY position", ACTIVE_STATES
            ).fetchall()
            jobs = [self._row_to_job(r) for r in rows]
            if include_done:
                done_rows = self._conn.execute(
                    "SELECT * FROM jobs WHERE state NOT IN (?,?) ORDER BY id DESC", ACTIVE_STATES
                ).fetchall()
                jobs.extend(self._row_to_job(r) for r in done_rows)
            return jobs

    def active_count(self) -> int:
        with self._open():
            row = self._conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE state IN (?,?)", ACTIVE_STATES
            ).fetchone()
            return row[0]

    def next_due(self, now: datetime | None = None) -> QueuedJob | None:
        if self.paused:
            return None
        now = now if now is not None else self._clock()
        now_iso = now.isoformat(timespec="seconds")
        with self._open():
            rows = self._conn.execute(
                "SELECT * FROM jobs WHERE state='wartet' ORDER BY position"
            ).fetchall()
            for row in rows:
                if row["next_try"] is None or row["next_try"] <= now_iso:
                    return self._row_to_job(row)
            return None

    def mark_running(self, job_id: int) -> None:
        with self._open():
            self._get_row(job_id)
            self._conn.execute(
                "UPDATE jobs SET state='läuft', attempts=attempts+1 WHERE id=?", (job_id,)
            )
            self._conn.commit()

    def mark_done(self, job_id: int, history_id: int | None) -> None:
        with self._open():
            self._get_row(job_id)
            self._conn.execute(
                "UPDATE jobs SET state='fertig', history_id=?, payload_json=NULL WHERE id=?",
                (history_id, job_id),
            )
            self._conn.commit()
            self._memory.pop(job_id, None)

    def mark_retry(self, job_id: int, error: str, next_try: datetime) -> None:
        with self._open():
            self._get_row(job_id)
            self._conn.execute(
                "UPDATE jobs SET state='wartet', last_error=?, next_try=? WHERE id=?",
                (error, _iso(next_try), job_id),
            )
            self._conn.commit()

    def mark_failed(self, job_id: int, error: str) -> None:
        with self._open():
            self._get_row(job_id)
            self._conn.execute(
                "UPDATE jobs SET state='fehler', last_error=?, payload_json=NULL WHERE id=?",
                (error, job_id),
            )
            self._conn.commit()
            self._memory.pop(job_id, None)

    def cancel(self, job_id: int) -> bool:
        with self._open():
            row = self._conn.execute("SELECT state FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None or row["state"] not in ACTIVE_STATES:
                return False
            self._conn.execute(
                "UPDATE jobs SET state='abgebrochen', payload_json=NULL WHERE id=?", (job_id,)
            )
            self._renumber_active_locked()
            self._conn.commit()
            self._memory.pop(job_id, None)
            return True

    def duplicate(self, job_id: int) -> int:
        with self._open():
            row = self._get_row(job_id)
            if row["sensitive"]:
                if job_id not in self._memory:
                    raise ValueError(_t("Sensibler Auftrag nach Neustart nicht mehr vorhanden"))
                payload = self._memory[job_id]
            else:
                if row["payload_json"] is None:
                    raise ValueError(
                        _t("Auftrag hat keine gespeicherten Daten mehr (bereits abgeschlossen)")
                    )
                payload = json.loads(row["payload_json"])
            created = self._clock()
            position = self._next_position_locked()
            payload_json = None if row["sensitive"] else json.dumps(payload, ensure_ascii=False)
            cur = self._conn.execute(
                "INSERT INTO jobs(created, source, title, state, position, attempts, next_try, "
                "last_error, sensitive, history_id, payload_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (created.isoformat(timespec="seconds"), row["source"], row["title"], "wartet",
                 position, 0, None, "", row["sensitive"], None, payload_json),
            )
            new_id = cur.lastrowid
            self._conn.commit()
            if row["sensitive"]:
                self._memory[new_id] = payload
            return new_id

    def move(self, job_id: int, position: int) -> None:
        with self._open():
            row = self._get_row(job_id)
            if row["state"] not in ACTIVE_STATES:
                raise KeyError(_t("Warteschlangen-Auftrag {job_id} ist nicht aktiv", job_id=job_id))
            rows = self._conn.execute(
                "SELECT id FROM jobs WHERE state IN (?,?) ORDER BY position", ACTIVE_STATES
            ).fetchall()
            ids = [r["id"] for r in rows]
            ids.remove(job_id)
            target = max(0, min(position, len(ids)))
            ids.insert(target, job_id)
            for pos, jid in enumerate(ids):
                self._conn.execute("UPDATE jobs SET position=? WHERE id=?", (pos, jid))
            self._conn.commit()

    def retry_now(self, job_id: int | None = None) -> None:
        with self._open():
            if job_id is None:
                self._conn.execute(
                    "UPDATE jobs SET next_try=NULL WHERE state IN (?,?)", ACTIVE_STATES
                )
            else:
                self._get_row(job_id)
                self._conn.execute("UPDATE jobs SET next_try=NULL WHERE id=?", (job_id,))
            self._conn.commit()

    @property
    def paused(self) -> bool:
        with self._open():
            row = self._conn.execute("SELECT value FROM meta WHERE key='paused'").fetchone()
            return row is not None and row["value"] == "1"

    def pause(self) -> None:
        with self._open():
            self._conn.execute(
                "INSERT INTO meta(key, value) VALUES ('paused', '1') "
                "ON CONFLICT(key) DO UPDATE SET value='1'"
            )
            self._conn.commit()

    def resume(self) -> None:
        with self._open():
            self._conn.execute(
                "INSERT INTO meta(key, value) VALUES ('paused', '0') "
                "ON CONFLICT(key) DO UPDATE SET value='0'"
            )
            self._conn.commit()

    def purge_done(self, older_than: timedelta = timedelta(days=7)) -> int:
        cutoff = self._clock() - older_than
        cutoff_iso = cutoff.isoformat(timespec="seconds")
        with self._open():
            rows = self._conn.execute(
                "SELECT id FROM jobs WHERE state NOT IN (?,?) AND created<?",
                (*ACTIVE_STATES, cutoff_iso),
            ).fetchall()
            ids = [r["id"] for r in rows]
            if ids:
                placeholders = ",".join("?" * len(ids))
                self._conn.execute(f"DELETE FROM jobs WHERE id IN ({placeholders})", ids)
                self._conn.commit()
                for jid in ids:
                    self._memory.pop(jid, None)
            return len(ids)

    def earliest_next_try(self) -> datetime | None:
        with self._open():
            row = self._conn.execute(
                "SELECT MIN(next_try) FROM jobs WHERE state='wartet' AND next_try IS NOT NULL"
            ).fetchone()
            return _from_iso(row[0]) if row and row[0] is not None else None

    @property
    def closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        """Schließt die Verbindung, sobald kein anderer Thread mehr zugreift; mehrfach aufrufbar."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._conn.close()

    def __enter__(self) -> "JobQueue":
        return self

    def __exit__(self, *exc) -> bool:
        self.close()
        return False
