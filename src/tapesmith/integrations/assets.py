"""Asset-Register mit zentralem Nummernkreis und Kurz-Link-Kopplung.

Fortlaufende Asset-Nummern (Standard `HL-0042`, optional mit Luhn-Prüfziffer `HL-0042-2`) kommen
genau einmal aus dem zentralen Nummernkreis `asset` (`numbering.NumberRanges`) und werden in
einem eigenen SQLite-Register mit Bezeichnung, Kategorie, Standort, Seriennummer, Host, Ziel-URL
und Paperless-Dokument gespeichert. Fehldrucke bekommen den Status `verworfen`, die Nummer wird
auch im Nummernkreis als verworfen vermerkt (nie erneut vergeben).
"""

from __future__ import annotations

import csv
import io
import re
import sqlite3
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from pathlib import Path

from tapesmith.integrations import settings, shortlink
from tapesmith.integrations.errors import NotConfigured
from tapesmith.numbering import NumberRange, NumberRanges
from tapesmith.i18n import _t

STATUSES = ("aktiv", "verworfen", "ausgemustert")

_UPDATABLE_FIELDS = ("bezeichnung", "kategorie", "standort", "seriennummer", "host", "ziel",
                     "paperless_doc", "status", "notiz")
_NUM_RE = re.compile(r"(\d+)")


def _natural_key(text: str) -> tuple:
    return tuple(int(part) if part.isdigit() else part.lower() for part in _NUM_RE.split(text) if part)


def _normalize_id(raw: str) -> str:
    return str(raw).strip().upper()


def _normalize_serial(raw: str) -> str:
    return re.sub(r"\s+", "", raw or "").upper()


@dataclass(frozen=True)
class Asset:
    id: str
    bezeichnung: str
    kategorie: str
    standort: str
    seriennummer: str
    host: str
    ziel: str | None
    paperless_doc: int | None
    status: str
    notiz: str
    created: str
    updated: str


# ---------- Prüfziffer (Luhn) ----------

def luhn_digit(digits: str) -> str:
    """Luhn-Prüfziffer über eine Ziffernfolge (ohne Präfix), z. B. "7992739871" -> "3"."""
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return str((10 - total % 10) % 10)


def format_id(prefix: str, width: int, n: int, *, check_digit: bool) -> str:
    """Asset-Nummer aus Präfix, Breite und laufender Zahl, optional mit Luhn-Prüfziffer."""
    digits = f"{n:0{width}d}"
    base = f"{prefix}{digits}"
    if check_digit:
        base = f"{base}-{luhn_digit(digits)}"
    return base


def verify_id(asset_id: str, prefix: str, *, check_digit: bool) -> bool:
    """Ob `asset_id` zu `prefix` passt (und, mit `check_digit`, die Prüfziffer stimmt)."""
    if not asset_id.startswith(prefix):
        return False
    rest = asset_id[len(prefix):]
    if check_digit:
        digits, sep, check = rest.rpartition("-")
        if not sep or not digits.isdigit() or not re.fullmatch(r"\d", check):
            return False
        return luhn_digit(digits) == check
    return rest.isdigit()


# ---------- Nummernkreis ----------

def ensure_range(ranges: NumberRanges, data: dict) -> NumberRange:
    """Nummernkreis `assets.range` (Standard `asset`) anlegen, falls er fehlt; sonst Präfix und
    Breite gegen `homelab.json` prüfen."""
    cfg = data["assets"]
    key = cfg["range"]
    try:
        current = ranges.get(key)
    except KeyError:
        return ranges.define(key, start=1, prefix=cfg["prefix"], width=cfg["width"])
    if current.prefix != cfg["prefix"] or current.width != cfg["width"]:
        raise ValueError(
            _t("Nummernkreis {key!r} hat Präfix {prefix!r} und Breite {width}, homelab.json sagt Präfix {prefix2!r} und Breite {width2}", key=key, prefix=current.prefix, width=current.width, prefix2=cfg['prefix'], width2=cfg['width']))
    return current


def peek_next_ids(ranges: NumberRanges, data: dict, count: int = 1) -> list[str]:
    """Nächste `count` Asset-Nummern, ohne sie zu reservieren (für Vorschau/Anzeige)."""
    cfg = data["assets"]
    prefix, width = cfg["prefix"], cfg["width"]
    check_digit = bool(cfg.get("check_digit", False))
    try:
        start = ranges.get(cfg["range"]).next
    except KeyError:
        start = 1
    return [format_id(prefix, width, start + i, check_digit=check_digit) for i in range(count)]


# ---------- Register (SQLite) ----------

_SCHEMA = """CREATE TABLE IF NOT EXISTS assets(
    id TEXT PRIMARY KEY,
    bezeichnung TEXT NOT NULL,
    kategorie TEXT NOT NULL,
    standort TEXT NOT NULL,
    seriennummer TEXT NOT NULL,
    host TEXT NOT NULL,
    ziel TEXT,
    paperless_doc INTEGER,
    status TEXT NOT NULL,
    notiz TEXT NOT NULL,
    created TEXT NOT NULL,
    updated TEXT NOT NULL
);"""


class AssetStore:
    def __init__(self, path: Path | None = None, *, clock: Callable[[], datetime] = datetime.now):
        self.path = Path(path) if path is not None else settings.data_dir() / "assets.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._clock = clock
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.execute(_SCHEMA)
            self._conn.commit()

    def _row_to_asset(self, row: sqlite3.Row) -> Asset:
        return Asset(id=row["id"], bezeichnung=row["bezeichnung"], kategorie=row["kategorie"],
                     standort=row["standort"], seriennummer=row["seriennummer"], host=row["host"],
                     ziel=row["ziel"], paperless_doc=row["paperless_doc"], status=row["status"],
                     notiz=row["notiz"], created=row["created"], updated=row["updated"])

    def _insert(self, asset_id: str, *, bezeichnung: str, kategorie: str, standort: str,
               seriennummer: str, host: str, ziel: str | None, paperless_doc: int | None,
               status: str, notiz: str, when: str) -> Asset:
        with self._lock:
            self._conn.execute(
                "INSERT INTO assets(id, bezeichnung, kategorie, standort, seriennummer, host, ziel, "
                "paperless_doc, status, notiz, created, updated) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (asset_id, bezeichnung, kategorie, standort, seriennummer, host, ziel, paperless_doc,
                 status, notiz, when, when))
            self._conn.commit()
        return Asset(id=asset_id, bezeichnung=bezeichnung, kategorie=kategorie, standort=standort,
                     seriennummer=seriennummer, host=host, ziel=ziel, paperless_doc=paperless_doc,
                     status=status, notiz=notiz, created=when, updated=when)

    def reserve(self, ranges: NumberRanges, data: dict, count: int = 1, *, bezeichnung: str = "",
               kategorie: str = "", standort: str = "", seriennummer: str = "", host: str = "",
               ziel: str | None = None, paperless_doc: int | None = None, notiz: str = "") -> list[Asset]:
        """`count` neue Nummern reservieren und als Zeilen mit Status `aktiv` anlegen."""
        if not 1 <= count <= 200:
            raise ValueError(_t("'count' muss 1..200 sein, ist {count}", count=count))
        r = ensure_range(ranges, data)
        cfg = data["assets"]
        check_digit = bool(cfg.get("check_digit", False))
        prefix = r.prefix
        numbers = ranges.reserve(r.key, count)
        when = self._clock().isoformat(timespec="seconds")
        result = []
        for plain in numbers:
            digits = plain[len(prefix):]
            asset_id = f"{plain}-{luhn_digit(digits)}" if check_digit else plain
            result.append(self._insert(asset_id, bezeichnung=bezeichnung, kategorie=kategorie,
                                       standort=standort, seriennummer=seriennummer, host=host,
                                       ziel=ziel, paperless_doc=paperless_doc, status="aktiv",
                                       notiz=notiz, when=when))
        return result

    def add_existing(self, asset_id: str, **fields_in) -> Asset:
        """Übernahme einer schon geklebten Nummer (ohne Nummernkreis-Reservierung)."""
        asset_id = _normalize_id(asset_id)
        if self.get(asset_id) is not None:
            raise ValueError(_t("Asset {asset_id!r} existiert bereits", asset_id=asset_id))
        unknown = set(fields_in) - set(_UPDATABLE_FIELDS)
        if unknown:
            raise KeyError(_t("Unbekannte Felder: {items}", items=', '.join(sorted(unknown))))
        when = self._clock().isoformat(timespec="seconds")
        values = {
            "bezeichnung": "", "kategorie": "", "standort": "", "seriennummer": "", "host": "",
            "ziel": None, "paperless_doc": None, "notiz": "",
        }
        values.update(fields_in)
        return self._insert(asset_id, bezeichnung=values["bezeichnung"], kategorie=values["kategorie"],
                            standort=values["standort"], seriennummer=values["seriennummer"],
                            host=values["host"], ziel=values["ziel"],
                            paperless_doc=values["paperless_doc"], status="aktiv",
                            notiz=values["notiz"], when=when)

    def get(self, asset_id: str) -> Asset | None:
        asset_id = _normalize_id(asset_id)
        with self._lock:
            row = self._conn.execute("SELECT * FROM assets WHERE id=?", (asset_id,)).fetchone()
        return self._row_to_asset(row) if row is not None else None

    def update(self, asset_id: str, **fields_in) -> Asset:
        asset_id = _normalize_id(asset_id)
        unknown = set(fields_in) - set(_UPDATABLE_FIELDS)
        if unknown:
            raise KeyError(_t("Unbekannte Felder: {items}", items=', '.join(sorted(unknown))))
        asset = self.get(asset_id)
        if asset is None:
            raise KeyError(_t("Asset {asset_id!r} gibt es nicht", asset_id=asset_id))
        if "status" in fields_in and fields_in["status"] not in STATUSES:
            raise ValueError(_t("status muss einer von {statuses} sein, ist {status!r}", statuses=STATUSES, status=fields_in['status']))
        merged = asdict(asset)
        merged.update(fields_in)
        when = self._clock().isoformat(timespec="seconds")
        with self._lock:
            self._conn.execute(
                "UPDATE assets SET bezeichnung=?, kategorie=?, standort=?, seriennummer=?, host=?, "
                "ziel=?, paperless_doc=?, status=?, notiz=?, updated=? WHERE id=?",
                (merged["bezeichnung"], merged["kategorie"], merged["standort"], merged["seriennummer"],
                 merged["host"], merged["ziel"], merged["paperless_doc"], merged["status"],
                 merged["notiz"], when, asset_id))
            self._conn.commit()
        return self.get(asset_id)

    def void(self, ranges: NumberRanges, data: dict, asset_id: str, reason: str) -> Asset:
        """Status auf `verworfen` setzen und die Nummer im Nummernkreis als verworfen vermerken."""
        asset_id = _normalize_id(asset_id)
        asset = self.get(asset_id)
        if asset is None:
            raise KeyError(_t("Asset {asset_id!r} gibt es nicht", asset_id=asset_id))
        r = ensure_range(ranges, data)
        check_digit = bool(data["assets"].get("check_digit", False))
        body = asset.id[len(r.prefix):] if asset.id.startswith(r.prefix) else asset.id
        digits = body.rpartition("-")[0] if check_digit and "-" in body else body
        ranges.void(r.key, f"{r.prefix}{digits}", reason)
        notiz = f"{asset.notiz}\n" if asset.notiz else ""
        notiz += _t("Verworfen: {reason}", reason=reason)
        return self.update(asset_id, status="verworfen", notiz=notiz)

    def list(self, *, status: str | None = None, query: str = "") -> list[Asset]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM assets").fetchall()
        assets = [self._row_to_asset(r) for r in rows]
        if status is not None:
            assets = [a for a in assets if a.status == status]
        words = [w.lower() for w in query.split()]
        if words:
            def matches(a: Asset) -> bool:
                fields_text = " ".join([a.id, a.bezeichnung, a.kategorie, a.standort,
                                        a.seriennummer, a.host, a.notiz]).lower()
                return all(w in fields_text for w in words)

            assets = [a for a in assets if matches(a)]
        return sorted(assets, key=lambda a: _natural_key(a.id))

    def find_by_serial(self, serial: str) -> list[Asset]:
        target = _normalize_serial(serial)
        return [a for a in self.list() if _normalize_serial(a.seriennummer) == target]

    def export_csv(self) -> str:
        buf = io.StringIO()
        buf.write("﻿")
        field_names = [f.name for f in fields(Asset)]
        writer = csv.writer(buf, delimiter=";")
        writer.writerow(field_names)
        for asset in self.list():
            row = asdict(asset)
            writer.writerow(["" if row[name] is None else row[name] for name in field_names])
        return buf.getvalue()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> "AssetStore":
        return self

    def __exit__(self, *exc) -> bool:
        self.close()
        return False


# ---------- Label ----------

def label_values(asset: Asset, link: str) -> dict[str, str]:
    return {"nummer": asset.id, "bezeichnung": asset.bezeichnung, "link": link}


def asset_link(data: dict, asset: Asset, *, sync: bool = True, client=None, keyring_module=None,
               environ=None, transport=None) -> tuple[str, list[str]]:
    """Inhalt für den QR-Code eines Assets: Kurz-Link (Dienst eingerichtet) oder das lange Ziel
    (Dienst nicht eingerichtet, mit Warnung). Ohne Dienst und ohne Ziel: `NotConfigured`.
    `sync=False` rechnet nur die Kurz-URL aus (Vorschau, ohne Netz), siehe `shortlink.link_for`."""
    if shortlink.configured(data):
        link = shortlink.link_for(data, asset.id, asset.ziel, note=asset.bezeichnung, sync=sync, client=client,
                                  keyring_module=keyring_module, environ=environ, transport=transport)
        return link, []
    if asset.ziel:
        return asset.ziel, [_t("Kurz-Link-Dienst nicht eingerichtet, QR enthält die lange Adresse")]
    raise NotConfigured(shortlink.SERVICE, _t("nicht eingerichtet und kein Ziel für {id}", id=asset.id),
                        hint=_t("In homelab.json 'shortlink.base_url' eintragen oder ein Ziel setzen"))
