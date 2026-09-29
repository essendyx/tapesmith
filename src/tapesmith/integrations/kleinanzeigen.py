"""Kleinanzeigen-Artikel-Tracking.

Verkaufsartikel mit Kurz-ID aus dem Nummernkreis `ka` (Standard `KA-017`), Titel, optional Preis
und Anzeigen-URL. Status `verfügbar`, `reserviert` (mit Name und Frist) und `verkauft` (mit Name
und Datum). Das Artikel-Etikett `ka-artikel` trägt einen QR auf die Anzeige bzw. einen Kurz-Link
mit derselben ID (`integrations.shortlink`); aus einem reservierten Artikel entsteht das
vorhandene Etikett `reserviert` unverändert weiter.

SQLite-Muster wie `inventory.InventoryStore`: eigene Sperre, kein Qt, kein argparse.
"""

from __future__ import annotations

import dataclasses
import re
import sqlite3
import threading
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path

from tapesmith.integrations import settings, shortlink
from tapesmith.numbering import NumberRange, NumberRanges
from tapesmith.i18n import _t

STATUSES = ("verfügbar", "reserviert", "verkauft")

_NUM_RE = re.compile(r"(\d+)")
_URL_RE = re.compile(r"^https?://\S+$")


def _natural_key(text: str) -> tuple:
    return tuple(int(part) if part.isdigit() else part.lower() for part in _NUM_RE.split(text) if part)


@dataclasses.dataclass(frozen=True)
class Artikel:
    id: str
    titel: str
    preis: str
    anzeige: str | None
    status: str
    name: str
    datum: str
    ort: str
    notiz: str
    created: str
    updated: str


def ensure_range(ranges: NumberRanges, data: dict) -> NumberRange:
    """Nummernkreis `kleinanzeigen.range` sicherstellen (wie Assets): fehlt er, wird er mit den
    Werten aus `homelab.json` angelegt (`start=1`); gibt es ihn schon, müssen Präfix und Breite
    übereinstimmen, sonst `ValueError`."""
    section = data["kleinanzeigen"]
    key, prefix, width = section["range"], section["prefix"], section["width"]
    try:
        current = ranges.get(key)
    except KeyError:
        return ranges.define(key, start=1, prefix=prefix, width=width)
    if current.prefix != prefix or current.width != width:
        raise ValueError(
            _t("Nummernkreis '{key}': Präfix/Breite weicht von homelab.json ab (vorhanden {prefix!r}/{width}, erwartet {prefix2!r}/{width2})", key=key, prefix=current.prefix, width=current.width, prefix2=prefix, width2=width))
    return current


def normalize_id(raw: str, data: dict) -> str:
    """Kleinanzeigen-ID bereinigen: strip, Großbuchstaben; `"17"`, `"KA-17"` und `"ka17"` werden
    zu `"KA-017"` (Präfix und Breite aus `homelab.json`). Sonst `ValueError`."""
    section = data["kleinanzeigen"]
    prefix, width = section["prefix"], section["width"]
    value = str(raw).strip().upper()
    letters = prefix.upper().rstrip("-")
    rest = value[len(letters):] if letters and value.startswith(letters) else value
    rest = rest.lstrip("-")
    if not rest or not rest.isdigit():
        raise ValueError(_t("Ungültige Kleinanzeigen-ID {raw!r} (erlaubt: Zahl oder {prefix}<Zahl>)", raw=raw, prefix=prefix))
    return f"{prefix}{rest.zfill(width)}"


def _check_titel(titel: str) -> str:
    titel = titel.strip()
    if not titel or len(titel) > 60:
        raise ValueError(_t("Titel darf nicht leer sein und höchstens 60 Zeichen haben"))
    return titel


def _check_anzeige(anzeige: str | None) -> str | None:
    if anzeige is None or anzeige == "":
        return None
    if not _URL_RE.match(anzeige):
        raise ValueError(_t("Ungültige Anzeigen-Adresse {anzeige!r} (erwartet http:// oder https://)", anzeige=anzeige))
    return anzeige


def _check_name(name: str) -> str:
    name = name.strip()
    if not name or len(name) > 30:
        raise ValueError(_t("Name darf nicht leer sein und höchstens 30 Zeichen haben"))
    return name


_SCHEMA = """CREATE TABLE IF NOT EXISTS artikel(
    id TEXT PRIMARY KEY,
    titel TEXT NOT NULL,
    preis TEXT NOT NULL,
    anzeige TEXT,
    status TEXT NOT NULL,
    name TEXT NOT NULL,
    datum TEXT NOT NULL,
    ort TEXT NOT NULL,
    notiz TEXT NOT NULL,
    created TEXT NOT NULL,
    updated TEXT NOT NULL
);"""


class KaStore:
    """SQLite-Ablage der Kleinanzeigen-Artikel unter `settings.data_dir() / "kleinanzeigen.sqlite3"`."""

    def __init__(self, path: Path | None = None, *, clock: Callable[[], datetime] = datetime.now):
        self.path = Path(path) if path is not None else settings.data_dir() / "kleinanzeigen.sqlite3"
        self._clock = clock
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute(_SCHEMA)
            self._conn.commit()

    # ---------- intern ----------

    def _row_to_artikel(self, row: sqlite3.Row) -> Artikel:
        return Artikel(id=row["id"], titel=row["titel"], preis=row["preis"], anzeige=row["anzeige"],
                       status=row["status"], name=row["name"], datum=row["datum"], ort=row["ort"],
                       notiz=row["notiz"], created=row["created"], updated=row["updated"])

    def _fetch(self, ka_id: str) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute("SELECT * FROM artikel WHERE id=?", (ka_id,)).fetchone()

    def _save(self, art: Artikel) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO artikel(id, titel, preis, anzeige, status, name, datum, ort, "
                "notiz, created, updated) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (art.id, art.titel, art.preis, art.anzeige, art.status, art.name, art.datum, art.ort,
                 art.notiz, art.created, art.updated))
            self._conn.commit()

    def _require(self, ka_id: str) -> Artikel:
        art = self.get(ka_id)
        if art is None:
            raise KeyError(_t("Kleinanzeigen-Artikel {ka_id!r} gibt es nicht", ka_id=ka_id))
        return art

    # ---------- öffentlich ----------

    def draft(self, ranges: NumberRanges, data: dict, *, titel: str, preis: str = "",
              anzeige: str | None = None, ort: str = "", notiz: str = "") -> Artikel:
        """Artikel, wie ihn `add` jetzt anlegen würde, ohne Nummer zu vergeben oder zu speichern
        (für die Etikettenprüfung vor dem Anlegen). Ein fehlender Nummernkreis wird nicht angelegt."""
        titel = _check_titel(titel)
        anzeige = _check_anzeige(anzeige)
        section = data["kleinanzeigen"]
        try:
            current = ranges.get(section["range"])
        except KeyError:
            current = NumberRange(key=section["range"], prefix=section["prefix"], width=section["width"], next=1)
        now = self._clock().isoformat(timespec="seconds")
        return Artikel(id=current.format(current.next), titel=titel, preis=preis, anzeige=anzeige,
                       status="verfügbar", name="", datum="", ort=ort, notiz=notiz, created=now, updated=now)

    def add(self, ranges: NumberRanges, data: dict, *, titel: str, preis: str = "",
           anzeige: str | None = None, ort: str = "", notiz: str = "") -> Artikel:
        titel = _check_titel(titel)
        anzeige = _check_anzeige(anzeige)
        ensure_range(ranges, data)
        [ka_id] = ranges.reserve(data["kleinanzeigen"]["range"], 1)
        now = self._clock().isoformat(timespec="seconds")
        art = Artikel(id=ka_id, titel=titel, preis=preis, anzeige=anzeige, status="verfügbar",
                     name="", datum="", ort=ort, notiz=notiz, created=now, updated=now)
        self._save(art)
        return art

    def discard(self, ranges: NumberRanges, data: dict, ka_id: str, reason: str) -> None:
        """Rückbau eines eben angelegten Artikels: Eintrag löschen, Nummer im Kreis verwerfen."""
        with self._lock:
            self._conn.execute("DELETE FROM artikel WHERE id=?", (ka_id,))
            self._conn.commit()
        ranges.void(data["kleinanzeigen"]["range"], ka_id, reason)

    def get(self, ka_id: str) -> Artikel | None:
        normalized = normalize_id(ka_id, settings.load_settings())
        row = self._fetch(normalized)
        return self._row_to_artikel(row) if row is not None else None

    def update(self, ka_id: str, **fields) -> Artikel:
        allowed = {"titel", "preis", "anzeige", "ort", "notiz"}
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(_t("Unbekannte Felder: {sorted}", sorted=sorted(unknown)))
        current = self._require(ka_id)
        titel = _check_titel(fields["titel"]) if "titel" in fields else current.titel
        preis = fields.get("preis", current.preis)
        anzeige = _check_anzeige(fields["anzeige"]) if "anzeige" in fields else current.anzeige
        ort = fields.get("ort", current.ort)
        notiz = fields.get("notiz", current.notiz)
        updated = dataclasses.replace(current, titel=titel, preis=preis, anzeige=anzeige, ort=ort,
                                      notiz=notiz, updated=self._clock().isoformat(timespec="seconds"))
        self._save(updated)
        return updated

    def reserve(self, ka_id: str, name: str, bis: date) -> Artikel:
        current = self._require(ka_id)
        if current.status not in ("verfügbar", "reserviert"):
            raise ValueError(
                _t("Artikel {id} kann aus Status '{status}' nicht reserviert werden", id=current.id, status=current.status))
        name = _check_name(name)
        updated = dataclasses.replace(current, status="reserviert", name=name, datum=bis.strftime("%d.%m.%Y"),
                                      updated=self._clock().isoformat(timespec="seconds"))
        self._save(updated)
        return updated

    def sell(self, ka_id: str, name: str, on: date) -> Artikel:
        current = self._require(ka_id)
        if current.status == "verkauft":
            raise ValueError(_t("Artikel {id} ist bereits verkauft", id=current.id))
        name = _check_name(name)
        updated = dataclasses.replace(current, status="verkauft", name=name, datum=on.strftime("%d.%m.%Y"),
                                      updated=self._clock().isoformat(timespec="seconds"))
        self._save(updated)
        return updated

    def release(self, ka_id: str) -> Artikel:
        current = self._require(ka_id)
        if current.status != "reserviert":
            raise ValueError(_t("Artikel {id} ist nicht reserviert", id=current.id))
        updated = dataclasses.replace(current, status="verfügbar", name="", datum="",
                                      updated=self._clock().isoformat(timespec="seconds"))
        self._save(updated)
        return updated

    def list(self, *, status: str | None = None, query: str = "") -> list[Artikel]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM artikel").fetchall()
        items = [self._row_to_artikel(r) for r in rows]
        if status is not None:
            items = [a for a in items if a.status == status]
        words = [w for w in query.strip().lower().split() if w]
        if words:
            def matches(a: Artikel) -> bool:
                fields = f"{a.id} {a.titel} {a.notiz} {a.ort} {a.name}".lower()
                return all(w in fields for w in words)
            items = [a for a in items if matches(a)]
        return sorted(items, key=lambda a: _natural_key(a.id))

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> "KaStore":
        return self

    def __exit__(self, *exc) -> bool:
        self.close()
        return False


# ---------- Etiketten ----------

def article_link(data: dict, art: Artikel, *, sync: bool = True, client=None, keyring_module=None,
                 environ=None, transport=None) -> tuple[str, list[str]]:
    """Inhalt für den QR-Code des Artikel-Etiketts: Kurz-Link (Dienst eingerichtet) oder die
    Anzeigen-Adresse (mit Warnung). Ohne beides: `ValueError`.
    `sync=False` rechnet nur die Kurz-URL aus (Vorschau, ohne Netz), siehe `shortlink.link_for`."""
    warnings: list[str] = []
    if shortlink.configured(data):
        link = shortlink.link_for(data, art.id, art.anzeige, note=art.titel, sync=sync, client=client,
                                  keyring_module=keyring_module, environ=environ, transport=transport)
        return link, warnings
    if art.anzeige:
        warnings.append(_t("Kurz-Link-Dienst nicht eingerichtet, QR enthält die lange Anzeigen-Adresse"))
        return art.anzeige, warnings
    raise ValueError(_t("Für {id} fehlt die Anzeigen-Adresse", id=art.id))


def article_label(data: dict, art: Artikel, **kw) -> tuple[dict, list[str]]:
    """`{"template": "ka-artikel", "values": {...}}` plus Warnungen."""
    link, warnings = article_link(data, art, **kw)
    values = {"id": art.id, "titel": art.titel, "preis": art.preis, "link": link}
    return {"template": "ka-artikel", "values": values}, warnings


def reserved_label(art: Artikel) -> dict:
    """`{"template": "reserviert", "values": {"name", "bis"}}`; nur bei Status `reserviert`."""
    if art.status != "reserviert":
        raise ValueError(_t("Artikel {id} ist nicht reserviert", id=art.id))
    return {"template": "reserviert", "values": {"name": art.name, "bis": art.datum}}
