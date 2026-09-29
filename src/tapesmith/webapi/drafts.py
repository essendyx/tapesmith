"""Entwürfe für Editor-Tabs und Absturz-Wiederherstellung.

Jeder Entwurf liegt als `<App-Verzeichnis>/drafts/<id>.json` (atomar geschrieben) und enthält
`DraftInfo` plus `document`. Lebenszeichen je Fenster-Sitzung hält nur der Speicher des Dienstes
(`time.monotonic`, injizierbar): ein Entwurf einer fremden Sitzung ohne Lebenszeichen seit `alive_s`
(oder einer unbekannten Sitzung, etwa nach einem Neustart des Dienstes) gilt als verwaist und wird
zur Wiederherstellung angeboten. `last_heartbeat()` meldet prozessweit das jüngste Lebenszeichen
(die Update-Prüfung nutzt es für „Fenster offen“).
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from fastapi import HTTPException

from tapesmith.document.model import DocumentError, document_from_dict, document_to_dict
from tapesmith.fileutil import atomic_write_text
from tapesmith.webapi.errors import NotFound
from tapesmith.i18n import _t

log = logging.getLogger(__name__)

DRAFTS_DIR_NAME = "drafts"
ALIVE_S = 90
MAX_DRAFTS = 50
MAX_BYTES = 2_000_000
MAX_TITLE = 120

LEGACY_ID = "legacy-entwurf"
LEGACY_SESSION = "legacy"
LEGACY_TITLE = "Entwurf"
LEGACY_FILE = "_entwurf.p12doc.json"

_ID_RE = re.compile(r"^[A-Za-z0-9-]{8,64}$")
INFO_KEYS = ("id", "title", "doc_name", "dirty", "updated", "objects", "order", "session")

_beat_lock = threading.Lock()
_last_beat: float | None = None


def last_heartbeat() -> float | None:
    """Monotone Zeit des jüngsten Lebenszeichens irgendeiner Sitzung in diesem Prozess (oder None)."""
    with _beat_lock:
        return _last_beat


def _note_beat(when: float) -> None:
    global _last_beat
    with _beat_lock:
        _last_beat = when


def check_id(value, what: str | None = None) -> str:
    if not isinstance(value, str) or not _ID_RE.match(value):
        what = _t("Entwurfs-ID") if what is None else what
        raise ValueError(_t("{what} ungültig: 8 bis 64 Zeichen aus Buchstaben, Ziffern und '-'", what=what))
    return value


def check_session(value) -> str:
    return check_id(value, _t("Sitzung"))


def _info(data: dict) -> dict:
    return {key: data.get(key) for key in INFO_KEYS}


class DraftStore:
    """Ablage der Entwürfe in `root` plus Lebenszeichen der Sitzungen im Speicher."""

    def __init__(self, root: Path, *, clock: Callable[[], float] = time.monotonic,
                 now: Callable[[], datetime] = datetime.now, alive_s: float = ALIVE_S,
                 legacy_path: Path | None = None):
        self.root = Path(root)
        self._clock = clock
        self._now = now
        self.alive_s = alive_s
        self._legacy = (Path(legacy_path) if legacy_path is not None
                        else self.root.parent / "documents" / LEGACY_FILE)
        self._beats: dict[str, float] = {}
        self._lock = threading.RLock()
        self._migrated = False

    # ---------- Lebenszeichen ----------

    def heartbeat(self, session: str) -> None:
        check_session(session)
        when = self._clock()
        with self._lock:
            self._beats[session] = when
        _note_beat(when)

    def alive(self, session: str) -> bool:
        with self._lock:
            beat = self._beats.get(session)
        return beat is not None and self._clock() - beat <= self.alive_s

    # ---------- Dateien ----------

    def _path(self, draft_id: str) -> Path:
        return self.root / f"{check_id(draft_id)}.json"

    def _read(self, path: Path) -> dict | None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            log.warning("Entwurf %s nicht lesbar: %s", path.name, exc)
            return None
        return data if isinstance(data, dict) else None

    def _write(self, data: dict) -> None:
        text = json.dumps(data, ensure_ascii=False)
        if len(text.encode("utf-8")) > MAX_BYTES:
            raise HTTPException(413, _t("Entwurf zu groß (höchstens {value} MB)", value=MAX_BYTES // 1000000))
        self.root.mkdir(parents=True, exist_ok=True)
        atomic_write_text(self.root / f"{data['id']}.json", text)

    def _all(self) -> list[dict]:
        if not self.root.is_dir():
            return []
        out = []
        for path in self.root.glob("*.json"):
            if not _ID_RE.match(path.stem):
                continue
            data = self._read(path)
            if data is not None and data.get("id") == path.stem:
                out.append(data)
        return out

    # ---------- API ----------

    def list(self, session: str) -> dict:
        """`{"drafts", "own", "orphaned"}` aus Sicht der Sitzung `session` (sortiert nach
        `order`, dann `updated`). Der erste Aufruf je Store übernimmt die Altlast `_entwurf`."""
        check_session(session)
        with self._lock:
            if not self._migrated:
                self._migrated = True
                self.migrate_legacy()
            infos = [_info(d) for d in self._all()]
        infos.sort(key=lambda i: (i["order"] if isinstance(i["order"], int) else 0, str(i["updated"] or ""),
                                  i["id"]))
        own = [i for i in infos if i["session"] == session]
        orphaned = [i for i in infos if i["session"] != session and not self.alive(str(i["session"]))]
        return {"drafts": infos, "own": own, "orphaned": orphaned}

    def get(self, draft_id: str) -> dict:
        path = self._path(draft_id)
        data = self._read(path) if path.is_file() else None
        if data is None:
            raise NotFound(_t("Entwurf '{draft_id}' nicht gefunden", draft_id=draft_id))
        return data

    def put(self, draft_id: str, body: dict) -> dict:
        """Legt den Entwurf an oder ersetzt ihn; zählt als Lebenszeichen der Sitzung."""
        path = self._path(draft_id)
        session = check_session(body.get("session"))
        title = body.get("title", "")
        if not isinstance(title, str) or len(title) > MAX_TITLE:
            raise ValueError(_t("Titel muss ein Text mit höchstens {max_title} Zeichen sein", max_title=MAX_TITLE))
        doc_name = body.get("doc_name")
        if doc_name is not None and not isinstance(doc_name, str):
            raise ValueError(_t("doc_name muss ein Text oder null sein"))
        dirty = body.get("dirty", False)
        if not isinstance(dirty, bool):
            raise ValueError(_t("dirty muss true oder false sein"))
        order = body.get("order", 0)
        if isinstance(order, bool) or not isinstance(order, int):
            raise ValueError(_t("order muss eine ganze Zahl sein"))
        raw = body.get("document")
        if not isinstance(raw, dict):
            raise DocumentError(_t("Dokument muss ein JSON-Objekt sein"))
        document = document_from_dict(raw)
        with self._lock:
            if not path.is_file() and len(self._all()) >= MAX_DRAFTS:
                raise ValueError(_t("Zu viele Entwürfe (höchstens {max_drafts})", max_drafts=MAX_DRAFTS))
            data = {"id": draft_id, "title": title, "doc_name": doc_name, "dirty": dirty,
                    "updated": self._now().isoformat(timespec="seconds"), "objects": len(document.objects),
                    "order": order, "session": session, "document": document_to_dict(document)}
            self._write(data)
        self.heartbeat(session)
        return _info(data)

    def delete(self, draft_id: str) -> None:
        path = self._path(draft_id)
        with self._lock:
            path.unlink(missing_ok=True)

    def adopt(self, draft_id: str, session: str) -> dict:
        """Übernimmt den Entwurf in die Sitzung `session` (Wiederherstellung)."""
        check_session(session)
        with self._lock:
            data = self.get(draft_id)
            data["session"] = session
            self._write(data)
        self.heartbeat(session)
        return _info(data)

    def migrate_legacy(self) -> bool:
        """Macht aus `documents/_entwurf.p12doc.json` einmalig den verwaisten Entwurf
        `legacy-entwurf` (Sitzung `legacy`, Titel „Entwurf“, ungespeichert) und löscht das alte
        Dokument. Rückgabe: ob etwas übernommen wurde."""
        with self._lock:
            if not self._legacy.is_file():
                return False
            try:
                raw = json.loads(self._legacy.read_text(encoding="utf-8"))
                document = document_from_dict(raw)
            except (OSError, ValueError) as exc:
                log.warning("Alter Entwurf %s nicht übernommen: %s", self._legacy, exc)
                return False
            updated = datetime.fromtimestamp(self._legacy.stat().st_mtime).isoformat(timespec="seconds")
            data = {"id": LEGACY_ID, "title": LEGACY_TITLE, "doc_name": None, "dirty": True,
                    "updated": updated, "objects": len(document.objects), "order": 0,
                    "session": LEGACY_SESSION, "document": document_to_dict(document)}
            self._write(data)
            self._legacy.unlink(missing_ok=True)
            return True
