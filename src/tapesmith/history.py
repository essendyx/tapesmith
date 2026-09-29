"""Druckverlauf in SQLite: Aufzeichnung, Volltextsuche und Nachdruck-Quelle.

Jeder Druck landet als Zeile in `jobs` (Miniatur, Vorlage, Werte, Quelle, Länge, Ergebnis,
Zeitpunkt). Sensible Jobs (`meta.sensitive`) speichern weder Kopfbild noch `LabelSpec`, ihre
Miniatur wird verpixelt. Suche kombiniert FTS5-Präfixsuche (Wortgrenzen) mit einer LIKE-Suche
(findet Teilstrings mitten in einem Wert, z. B. eine Seriennummer), damit beide Fälle greifen.
"""

import json
import sqlite3
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path

from PIL import Image

from tapesmith import paths
from tapesmith.jobs import JobMeta
from tapesmith.templates.fill import REDACTED
from tapesmith.i18n import _t

SCHEMA_VERSION = 1
STATUSES = ("läuft", "ok", "abgebrochen", "unvollständig", "fehler")
THUMB_HEIGHT = 48
THUMB_MAX_WIDTH = 600

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS jobs(
    id INTEGER PRIMARY KEY,
    created TEXT NOT NULL,
    source TEXT NOT NULL,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    template TEXT,
    values_json TEXT NOT NULL,
    spec_json TEXT,
    length_mm REAL NOT NULL,
    tape_mm REAL NOT NULL,
    copies INTEGER NOT NULL,
    chained INTEGER NOT NULL,
    status TEXT NOT NULL,
    error TEXT NOT NULL,
    sensitive INTEGER NOT NULL,
    thumb_png BLOB,
    head_png BLOB
);
"""
INDEX_SQL = "CREATE INDEX IF NOT EXISTS jobs_created ON jobs(created);"
FTS_SQL = "CREATE VIRTUAL TABLE IF NOT EXISTS jobs_fts USING fts5(title, body, content='');"


@dataclass(frozen=True)
class HistoryEntry:
    id: int
    created: datetime
    source: str
    kind: str
    title: str
    template: str | None
    values: dict[str, str]
    spec: dict | None
    length_mm: float
    tape_mm: float
    copies: int
    chained: bool
    status: str
    error: str
    sensitive: bool
    has_head: bool

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "created": self.created.isoformat(),
            "source": self.source,
            "kind": self.kind,
            "title": self.title,
            "template": self.template,
            "values": dict(self.values),
            "spec": self.spec,
            "length_mm": self.length_mm,
            "tape_mm": self.tape_mm,
            "copies": self.copies,
            "chained": self.chained,
            "status": self.status,
            "error": self.error,
            "sensitive": self.sensitive,
            "has_head": self.has_head,
        }


@dataclass(frozen=True)
class ReprintSource:
    kind: str
    head: Image.Image | None
    template: str | None
    values: dict[str, str]
    missing: tuple[str, ...]


def _is_wifi_qr(entry: HistoryEntry) -> bool:
    """Sensibler WLAN-QR aus `labelmeta.qr_meta` mit allen Daten für den Nachdruck."""
    values = entry.values
    return (values.get("qr_kind") == "wifi" and values.get("password") == REDACTED
            and all(k in values for k in ("ssid", "security", "hidden", "qr_spec")))


def is_reprintable(entry: HistoryEntry) -> bool:
    """True, wenn `HistoryStore.reprint_source` für diesen Eintrag eine Quelle liefert."""
    return entry.has_head or bool(entry.template) or _is_wifi_qr(entry)


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _escape_fts_prefix_term(word: str) -> str:
    return f'"{word.replace(chr(34), chr(34) * 2)}"*'


def _landscape_or_from_head(landscape: Image.Image | None, head: Image.Image | None) -> Image.Image | None:
    if landscape is not None:
        return landscape
    if head is not None:
        return head.rotate(90, expand=True)
    return None


def _thumbnail_size(source: Image.Image) -> tuple[int, int]:
    scale = THUMB_HEIGHT / source.height
    width = max(1, min(round(source.width * scale), THUMB_MAX_WIDTH))
    return width, THUMB_HEIGHT


def _png_bytes(image: Image.Image) -> bytes:
    buf = BytesIO()
    image.save(buf, "PNG")
    return buf.getvalue()


class HistoryStore:
    def __init__(self, path: Path | None = None, clock: Callable[[], datetime] = datetime.now):
        self.path = Path(path) if path is not None else paths.history_db_path()
        self._clock = clock
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._fts_available = True
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.execute(SCHEMA_SQL)
            self._conn.execute(INDEX_SQL)
            try:
                self._conn.execute(FTS_SQL)
            except sqlite3.OperationalError:
                self._fts_available = False
            self._conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            self._conn.commit()

    def _thumbnail_bytes(self, meta: JobMeta, landscape: Image.Image | None,
                          head: Image.Image | None) -> bytes | None:
        source = _landscape_or_from_head(landscape, head)
        if source is None:
            return None
        gray = source.convert("L")
        if meta.sensitive:
            tiny = gray.resize((max(1, gray.width // 8), max(1, gray.height // 8)), Image.BOX)
            thumb = tiny.resize(_thumbnail_size(gray), Image.NEAREST)
        else:
            thumb = gray.resize(_thumbnail_size(gray), Image.NEAREST)
        return _png_bytes(thumb)

    def record(self, meta: JobMeta, *, landscape: Image.Image | None, head: Image.Image | None,
               length_mm: float, tape_mm: float, copies: int = 1, chained: bool = False,
               status: str = "läuft", error: str = "") -> int:
        if status not in STATUSES:
            raise ValueError(_t("Unbekannter Status '{status}' (erlaubt: {items})", status=status, items=', '.join(STATUSES)))
        created = self._clock()
        values_json = json.dumps(meta.values, ensure_ascii=False)
        thumb_png = self._thumbnail_bytes(meta, landscape, head)
        if meta.sensitive:
            spec_json = None
            head_png = None
        else:
            spec_json = json.dumps(meta.spec, ensure_ascii=False) if meta.spec is not None else None
            head_png = _png_bytes(head.convert("1")) if head is not None else None
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO jobs(created, source, kind, title, template, values_json, spec_json, "
                "length_mm, tape_mm, copies, chained, status, error, sensitive, thumb_png, head_png) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (created.isoformat(timespec="seconds"), meta.source, meta.kind, meta.title, meta.template,
                 values_json, spec_json, length_mm, tape_mm, copies, int(chained), status, error,
                 int(meta.sensitive), thumb_png, head_png),
            )
            entry_id = cur.lastrowid
            if self._fts_available:
                body = " ".join([meta.template or "", *meta.values.values()])
                self._conn.execute("INSERT INTO jobs_fts(rowid, title, body) VALUES (?, ?, ?)",
                                    (entry_id, meta.title, body))
            self._conn.commit()
        return entry_id

    def update_status(self, entry_id: int, status: str, error: str = "") -> None:
        if status not in STATUSES:
            raise ValueError(_t("Unbekannter Status '{status}' (erlaubt: {items})", status=status, items=', '.join(STATUSES)))
        with self._lock:
            cur = self._conn.execute("UPDATE jobs SET status=?, error=? WHERE id=?",
                                      (status, error, entry_id))
            self._conn.commit()
        if cur.rowcount == 0:
            raise KeyError(_t("Verlaufseintrag {entry_id} gibt es nicht", entry_id=entry_id))

    def _row_to_entry(self, row: sqlite3.Row) -> HistoryEntry:
        values = json.loads(row["values_json"])
        spec = json.loads(row["spec_json"]) if row["spec_json"] is not None else None
        return HistoryEntry(
            id=row["id"],
            created=datetime.fromisoformat(row["created"]),
            source=row["source"],
            kind=row["kind"],
            title=row["title"],
            template=row["template"],
            values=values,
            spec=spec,
            length_mm=row["length_mm"],
            tape_mm=row["tape_mm"],
            copies=row["copies"],
            chained=bool(row["chained"]),
            status=row["status"],
            error=row["error"],
            sensitive=bool(row["sensitive"]),
            has_head=row["head_png"] is not None,
        )

    def get(self, entry_id: int) -> HistoryEntry:
        with self._lock:
            row = self._conn.execute("SELECT * FROM jobs WHERE id=?", (entry_id,)).fetchone()
        if row is None:
            raise KeyError(_t("Verlaufseintrag {entry_id} gibt es nicht", entry_id=entry_id))
        return self._row_to_entry(row)

    def last(self, source: str | None = None) -> HistoryEntry | None:
        with self._lock:
            if source is None:
                row = self._conn.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT 1").fetchone()
            else:
                row = self._conn.execute(
                    "SELECT * FROM jobs WHERE source=? ORDER BY id DESC LIMIT 1", (source,)
                ).fetchone()
        return self._row_to_entry(row) if row is not None else None

    def search(self, query: str = "", limit: int = 50) -> list[HistoryEntry]:
        query = query.strip()
        if not query:
            with self._lock:
                rows = self._conn.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            return [self._row_to_entry(r) for r in rows]

        words = query.split()
        ids: set[int] = set()

        if self._fts_available:
            match = " AND ".join(_escape_fts_prefix_term(w) for w in words)
            with self._lock:
                try:
                    rows = self._conn.execute(
                        "SELECT rowid FROM jobs_fts WHERE jobs_fts MATCH ?", (match,)
                    ).fetchall()
                    ids.update(r[0] for r in rows)
                except sqlite3.OperationalError:
                    pass

        like_clauses = []
        like_params: list[str] = []
        for word in words:
            pattern = f"%{_escape_like(word)}%"
            like_clauses.append("(title LIKE ? ESCAPE '\\' OR values_json LIKE ? ESCAPE '\\')")
            like_params.extend([pattern, pattern])
        with self._lock:
            rows = self._conn.execute(
                f"SELECT id FROM jobs WHERE {' AND '.join(like_clauses)}", like_params
            ).fetchall()
            ids.update(r[0] for r in rows)

        if not ids:
            return []
        placeholders = ",".join("?" * len(ids))
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM jobs WHERE id IN ({placeholders}) ORDER BY id DESC LIMIT ?",
                (*ids, limit),
            ).fetchall()
        return [self._row_to_entry(r) for r in rows]

    def thumbnail(self, entry_id: int) -> Image.Image | None:
        with self._lock:
            row = self._conn.execute("SELECT thumb_png FROM jobs WHERE id=?", (entry_id,)).fetchone()
        if row is None:
            raise KeyError(_t("Verlaufseintrag {entry_id} gibt es nicht", entry_id=entry_id))
        data = row["thumb_png"]
        return Image.open(BytesIO(data)).convert("L") if data is not None else None

    def head_image(self, entry_id: int) -> Image.Image | None:
        with self._lock:
            row = self._conn.execute("SELECT head_png FROM jobs WHERE id=?", (entry_id,)).fetchone()
        if row is None:
            raise KeyError(_t("Verlaufseintrag {entry_id} gibt es nicht", entry_id=entry_id))
        data = row["head_png"]
        return Image.open(BytesIO(data)).convert("1") if data is not None else None

    def iter_entries(self, *, since: datetime | None = None, until: datetime | None = None,
                     batch: int = 500) -> Iterator[HistoryEntry]:
        """Alle Einträge (älteste zuerst), `created` in [since, until), seitenweise per
        id-Cursor (kein OFFSET), für Statistik über große Verläufe. Der Lock wird nur je
        Seite gehalten, nicht für die gesamte Iteration."""
        clauses = ["id > ?"]
        params: list = []
        if since is not None:
            clauses.append("created >= ?")
        if until is not None:
            clauses.append("created < ?")
        query = f"SELECT * FROM jobs WHERE {' AND '.join(clauses)} ORDER BY id ASC LIMIT ?"
        last_id = 0
        while True:
            params = [last_id]
            if since is not None:
                params.append(since.isoformat(timespec="seconds"))
            if until is not None:
                params.append(until.isoformat(timespec="seconds"))
            params.append(batch)
            with self._lock:
                rows = self._conn.execute(query, params).fetchall()
            if not rows:
                return
            for row in rows:
                yield self._row_to_entry(row)
            last_id = rows[-1]["id"]

    def usage_since(self, source: str, since: datetime) -> tuple[int, float]:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(tape_mm), 0) FROM jobs "
                "WHERE source=? AND created>=? AND status != 'fehler'",
                (source, since.isoformat(timespec="seconds")),
            ).fetchone()
        return int(row[0]), float(row[1])

    def reprint_source(self, entry_id: int) -> ReprintSource:
        entry = self.get(entry_id)
        if entry.has_head:
            head = self.head_image(entry_id)
            return ReprintSource("head", head, entry.template, entry.values, ())
        if _is_wifi_qr(entry):
            values = {k: v for k, v in entry.values.items() if v != REDACTED and k != "qr"}
            return ReprintSource("qr-wifi", None, None, values, ("password",))
        if entry.template:
            values = {k: v for k, v in entry.values.items() if v != REDACTED and not k.endswith("_model")}
            missing = tuple(k for k, v in entry.values.items() if v == REDACTED and not k.endswith("_model"))
            return ReprintSource("template", None, entry.template, values, missing)
        raise ValueError(_t("Eintrag {entry_id} kann nicht nachgedruckt werden (sensibler Inhalt ohne Vorlage)", entry_id=entry_id))

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> "HistoryStore":
        return self

    def __exit__(self, *exc) -> bool:
        self.close()
        return False
