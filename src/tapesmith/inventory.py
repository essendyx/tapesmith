"""Inventarlisten: Boxen mit Inhalt, Verleihliste, Label-Druck.

Bewusst schlank (kein Homebox/Grocy): Boxen (`BOX-07`, Ort) mit Gegenständen, eine einfache
Verleihliste (Gegenstand an Person, seit/bis, Rückgabe) und drei Label-Arten über die
vorhandene Vorlage `aufbewahrungsbox` (Box-Label) bzw. freie Textzeilen (Inhalt, Verleih).

SQLite-Muster wie `history.py`: eigene Sperre, `check_same_thread=False`, WAL, `busy_timeout`.
Kein Qt, kein argparse; gedruckt wird hier nichts, nur gerendert.
"""

import re
import sqlite3
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from tapesmith import paths
from tapesmith.device.profile import DeviceProfile
from tapesmith.document.render import render_spec
from tapesmith.jobs import JobMeta, spec_to_dict
from tapesmith.render.compose import LabelSpec, RenderResult
from tapesmith.tape.profiles import TapeProfile
from tapesmith.templates.fill import CounterStore, resolve_values
from tapesmith.templates.render import render_meta, render_template
from tapesmith.templates.store import find_template
from tapesmith.i18n import _t

BOX_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,15}$")

MAX_LINE_CHARS = 32
_NUM_RE = re.compile(r"(\d+)")


def _natural_key(text: str) -> tuple:
    return tuple(int(part) if part.isdigit() else part.lower() for part in _NUM_RE.split(text) if part)


@dataclass(frozen=True)
class Box:
    id: str
    location: str
    note: str
    created: datetime


@dataclass(frozen=True)
class Item:
    id: int
    box_id: str | None
    name: str
    qty: int
    note: str


@dataclass(frozen=True)
class Loan:
    id: int
    item: str
    person: str
    since: date
    due: date | None
    returned: date | None
    note: str

    @property
    def open(self) -> bool:
        return self.returned is None

    def overdue(self, today: date) -> bool:
        return self.open and self.due is not None and self.due < today


@dataclass(frozen=True)
class SearchHit:
    item: Item
    box: Box | None

    def text(self) -> str:
        location = f"{self.box.id}, {self.box.location}" if self.box is not None else _t("ohne Box")
        return f"{self.item.name} ({self.item.qty}) → {location}"


_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS boxes(
        id TEXT PRIMARY KEY,
        location TEXT NOT NULL,
        note TEXT NOT NULL,
        created TEXT NOT NULL
    );""",
    """CREATE TABLE IF NOT EXISTS items(
        id INTEGER PRIMARY KEY,
        box_id TEXT,
        name TEXT NOT NULL,
        qty INTEGER NOT NULL,
        note TEXT NOT NULL
    );""",
    """CREATE TABLE IF NOT EXISTS loans(
        id INTEGER PRIMARY KEY,
        item TEXT NOT NULL,
        person TEXT NOT NULL,
        since TEXT NOT NULL,
        due TEXT,
        returned TEXT,
        note TEXT NOT NULL
    );""",
)


class InventoryStore:
    def __init__(self, path: Path | None = None, *, clock: Callable[[], datetime] = datetime.now):
        self.path = Path(path) if path is not None else paths.app_dir() / "inventory.sqlite3"
        self._clock = clock
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA busy_timeout=5000")
            for stmt in _SCHEMA:
                self._conn.execute(stmt)
            self._conn.commit()

    # ---------- Boxen ----------

    def add_box(self, box_id: str, location: str, note: str = "") -> Box:
        if not BOX_ID.match(box_id):
            raise ValueError(
                _t("Ungültige Box-ID {box_id!r} (erlaubt: Buchstaben/Ziffern/._- , 1-16 Zeichen)", box_id=box_id))
        created = self._clock()
        with self._lock:
            existing = self._conn.execute("SELECT 1 FROM boxes WHERE id=?", (box_id,)).fetchone()
            if existing is not None:
                raise ValueError(_t("Box {box_id!r} existiert bereits", box_id=box_id))
            self._conn.execute(
                "INSERT INTO boxes(id, location, note, created) VALUES (?,?,?,?)",
                (box_id, location, note, created.isoformat(timespec="seconds")))
            self._conn.commit()
        return Box(id=box_id, location=location, note=note, created=created)

    def update_box(self, box_id: str, *, location: str | None = None, note: str | None = None) -> Box:
        box = self.box(box_id)
        new_location = location if location is not None else box.location
        new_note = note if note is not None else box.note
        with self._lock:
            self._conn.execute("UPDATE boxes SET location=?, note=? WHERE id=?",
                               (new_location, new_note, box_id))
            self._conn.commit()
        return Box(id=box_id, location=new_location, note=new_note, created=box.created)

    def remove_box(self, box_id: str) -> None:
        self.box(box_id)
        with self._lock:
            count = self._conn.execute(
                "SELECT COUNT(*) FROM items WHERE box_id=?", (box_id,)).fetchone()[0]
            if count:
                raise ValueError(_t("Box enthält noch {count} Gegenstände", count=count))
            self._conn.execute("DELETE FROM boxes WHERE id=?", (box_id,))
            self._conn.commit()

    def _row_to_box(self, row: sqlite3.Row) -> Box:
        return Box(id=row["id"], location=row["location"], note=row["note"],
                   created=datetime.fromisoformat(row["created"]))

    def boxes(self) -> list[Box]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM boxes").fetchall()
        return sorted((self._row_to_box(r) for r in rows), key=lambda b: _natural_key(b.id))

    def box(self, box_id: str) -> Box:
        with self._lock:
            row = self._conn.execute("SELECT * FROM boxes WHERE id=?", (box_id,)).fetchone()
        if row is None:
            raise KeyError(_t("Box {box_id!r} gibt es nicht", box_id=box_id))
        return self._row_to_box(row)

    # ---------- Gegenstände ----------

    def _row_to_item(self, row: sqlite3.Row) -> Item:
        return Item(id=row["id"], box_id=row["box_id"], name=row["name"], qty=row["qty"], note=row["note"])

    def _get_item_row(self, item_id: int) -> sqlite3.Row:
        with self._lock:
            row = self._conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
        if row is None:
            raise KeyError(_t("Gegenstand {item_id} gibt es nicht", item_id=item_id))
        return row

    def add_item(self, name: str, box_id: str | None = None, qty: int = 1, note: str = "") -> Item:
        name = name.strip()
        if not name or len(name) > 60:
            raise ValueError(_t("Name darf nicht leer sein und höchstens 60 Zeichen haben"))
        if qty < 1:
            raise ValueError(_t("qty muss ≥ 1 sein"))
        if box_id is not None:
            self.box(box_id)
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO items(box_id, name, qty, note) VALUES (?,?,?,?)",
                (box_id, name, qty, note))
            self._conn.commit()
            item_id = cur.lastrowid
        return Item(id=item_id, box_id=box_id, name=name, qty=qty, note=note)

    def move_item(self, item_id: int, box_id: str | None) -> Item:
        self._get_item_row(item_id)
        if box_id is not None:
            self.box(box_id)
        with self._lock:
            self._conn.execute("UPDATE items SET box_id=? WHERE id=?", (box_id, item_id))
            self._conn.commit()
        return self._row_to_item(self._get_item_row(item_id))

    def remove_item(self, item_id: int) -> None:
        self._get_item_row(item_id)
        with self._lock:
            self._conn.execute("DELETE FROM items WHERE id=?", (item_id,))
            self._conn.commit()

    def items(self, box_id: str | None = None) -> list[Item]:
        with self._lock:
            if box_id is None:
                rows = self._conn.execute("SELECT * FROM items ORDER BY id").fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM items WHERE box_id=? ORDER BY id", (box_id,)).fetchall()
        return [self._row_to_item(r) for r in rows]

    def search(self, query: str) -> list[SearchHit]:
        query = query.strip()
        if not query:
            return []
        words = [w.lower() for w in query.split()]
        with self._lock:
            item_rows = self._conn.execute("SELECT * FROM items ORDER BY id").fetchall()
            box_rows = self._conn.execute("SELECT * FROM boxes").fetchall()
        boxes_by_id = {r["id"]: self._row_to_box(r) for r in box_rows}
        hits: list[SearchHit] = []
        for row in item_rows:
            item = self._row_to_item(row)
            box = boxes_by_id.get(item.box_id) if item.box_id else None
            fields = [item.name.lower(), item.note.lower()]
            if box is not None:
                fields += [box.id.lower(), box.location.lower()]
            if all(any(w in f for f in fields) for w in words):
                hits.append(SearchHit(item, box))
        return hits

    # ---------- Verleih ----------

    def _row_to_loan(self, row: sqlite3.Row) -> Loan:
        return Loan(id=row["id"], item=row["item"], person=row["person"],
                   since=date.fromisoformat(row["since"]),
                   due=date.fromisoformat(row["due"]) if row["due"] else None,
                   returned=date.fromisoformat(row["returned"]) if row["returned"] else None,
                   note=row["note"])

    def _get_loan_row(self, loan_id: int) -> sqlite3.Row:
        with self._lock:
            row = self._conn.execute("SELECT * FROM loans WHERE id=?", (loan_id,)).fetchone()
        if row is None:
            raise KeyError(_t("Verleihposten {loan_id} gibt es nicht", loan_id=loan_id))
        return row

    def lend(self, item: str, person: str, *, since: date | None = None, due: date | None = None,
             note: str = "") -> Loan:
        since = since if since is not None else self._clock().date()
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO loans(item, person, since, due, returned, note) VALUES (?,?,?,?,?,?)",
                (item, person, since.isoformat(), due.isoformat() if due else None, None, note))
            self._conn.commit()
            loan_id = cur.lastrowid
        return Loan(id=loan_id, item=item, person=person, since=since, due=due, returned=None, note=note)

    def give_back(self, loan_id: int, *, on: date | None = None) -> Loan:
        row = self._get_loan_row(loan_id)
        if row["returned"] is not None:
            raise ValueError(_t("Verleihposten {loan_id} wurde schon zurückgegeben", loan_id=loan_id))
        on = on if on is not None else self._clock().date()
        with self._lock:
            self._conn.execute("UPDATE loans SET returned=? WHERE id=?", (on.isoformat(), loan_id))
            self._conn.commit()
        return self._row_to_loan(self._get_loan_row(loan_id))

    def loan(self, loan_id: int) -> Loan:
        """Einzelnen Verleihposten holen (für den Label-Druck)."""
        return self._row_to_loan(self._get_loan_row(loan_id))

    def loans(self, *, open_only: bool = True) -> list[Loan]:
        with self._lock:
            if open_only:
                rows = self._conn.execute(
                    "SELECT * FROM loans WHERE returned IS NULL ORDER BY since").fetchall()
            else:
                rows = self._conn.execute("SELECT * FROM loans ORDER BY since").fetchall()
        return [self._row_to_loan(r) for r in rows]

    # ---------- Verwaltung ----------

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> "InventoryStore":
        return self

    def __exit__(self, *exc) -> bool:
        self.close()
        return False


# ---------- Label-Inhalte ----------

def box_label_values(box: Box) -> dict[str, str]:
    return {"nummer": box.id, "ort": box.location}


def _item_desc(item: Item) -> str:
    return f"{item.qty}× {item.name}" if item.qty != 1 else item.name


def contents_lines(box: Box, items: Sequence[Item], max_lines: int = 3) -> tuple[str, ...]:
    """Zeile 1 die Box (Nummer · Ort), danach Gegenstände (", "-getrennt), auf `max_lines`
    Zeilen (≤ `MAX_LINE_CHARS` Zeichen je Zeile) umbrochen. Passt nicht alles hinein, endet die
    letzte Zeile mit „… (+N)“ (N = Anzahl nicht aufgeführter Gegenstände)."""
    lines = [f"{box.id} · {box.location}"]
    remaining = [_item_desc(it) for it in items]
    body_budget = max(max_lines - 1, 0)

    while remaining and len(lines) - 1 < body_budget:
        line = ""
        while remaining:
            candidate = remaining[0] if not line else f"{line}, {remaining[0]}"
            if len(candidate) <= MAX_LINE_CHARS:
                line = candidate
                remaining.pop(0)
            else:
                break
        if not line:
            line = remaining.pop(0)[:MAX_LINE_CHARS]
        lines.append(line)

    if remaining:
        count = len(remaining)
        last = lines[-1] if len(lines) > 1 else ""
        while True:
            suffix = f" … (+{count})"
            if len(last) + len(suffix) <= MAX_LINE_CHARS or not last:
                break
            if ", " in last:
                last, _dropped = last.rsplit(", ", 1)
                count += 1
            else:
                last = last[: max(0, MAX_LINE_CHARS - len(suffix))]
                break
        text = f"{last}{suffix}" if last else suffix.strip()
        if len(lines) > 1:
            lines[-1] = text
        else:
            lines.append(text)

    return tuple(lines)


def loan_lines(loan: Loan) -> tuple[str, ...]:
    line1 = _t("Verliehen an {person}", person=loan.person)
    line2 = f"seit {loan.since:%d.%m.%Y}"
    if loan.due is not None:
        line2 += _t(" · bis {due:%d.%m.%Y}", due=loan.due)
    return (line1, line2)


def render_box_label(box: Box, profile: DeviceProfile, *, counters: CounterStore,
                     tape: TapeProfile | None = None, now: datetime | None = None,
                     source: str = "gui") -> tuple[RenderResult, JobMeta, tuple[str, ...]]:
    """Box-Label über die Vorlage `aufbewahrungsbox` (QR + Nummer + Ort). `counters` ist
    Pflicht: CLI übergibt `numbering.counter_store(cfg)`, GUI `services.counters`. Die
    mitgelieferte Vorlage hat keinen Zähler; eine gleichnamige Benutzer-Vorlage darf einen haben,
    dann `counters.commit(key)` für jeden Schlüssel im dritten Rückgabewert nach dem Druck."""
    template = find_template("aufbewahrungsbox")
    when = now if now is not None else datetime.now()
    resolved = resolve_values(template, box_label_values(box), when, counters)
    tr = render_template(template, resolved.values, profile, tape=tape)
    meta = render_meta(tr, source=source)
    return tr.result, meta, resolved.counter_keys


def render_lines_label(lines: Sequence[str], profile: DeviceProfile, *,
                       tape: TapeProfile | None = None, title: str,
                       source: str = "gui") -> tuple[RenderResult, JobMeta]:
    spec = LabelSpec(lines=tuple(lines))
    result = render_spec(spec, profile, tape)
    meta = JobMeta(source=source, kind="text", title=title, spec=spec_to_dict(spec))
    return result, meta
