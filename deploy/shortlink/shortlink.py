"""Eigenständiger Kurz-Link-Redirect-Dienst.

`GET /<ID>` leitet per 302 auf das hinterlegte Ziel um, eine Admin-API unter
`/api/` (Bearer-Token aus der Umgebung) legt Links an, ändert, listet und
löscht sie, `/health` meldet den Zustand. Daten in SQLite. Dieses Modul ist
bewusst eigenständig: keine Importe aus `tapesmith`, eigene `requirements.txt`.

Aufruf über uvicorn: `uvicorn shortlink:factory --factory`. Ein bloßer Import
des Moduls (z. B. in Tests) legt keine App und keine Datei unter `/data` an;
`factory()` liest die Umgebungsvariablen erst beim Aufruf.
"""

from __future__ import annotations

import hmac
import logging
import os
import re
import sqlite3
import threading
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

logger = logging.getLogger("shortlink")

ID_RE = re.compile(r"^[0-9A-Z][0-9A-Z-]{0,15}$")
_BASE36_DIGITS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_MAX_TARGET_LEN = 2000
_MAX_NOTE_LEN = 200
_MIN_ADMIN_TOKEN_LEN = 24

try:  # pydantic ist eine Abhängigkeit von fastapi, daher immer vorhanden.
    from pydantic import BaseModel
except ImportError as exc:  # pragma: no cover
    raise SystemExit("pydantic fehlt (kommt mit fastapi)") from exc


class LinkCreate(BaseModel):
    target: str | None = None
    id: str | None = None
    note: str = ""


class LinkUpdate(BaseModel):
    target: str | None = None
    note: str | None = None


def _to_base36(n: int) -> str:
    if n == 0:
        return "0"
    digits = []
    while n:
        n, rest = divmod(n, 36)
        digits.append(_BASE36_DIGITS[rest])
    return "".join(reversed(digits))


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def validate_target(target: str) -> None:
    if not target or len(target) > _MAX_TARGET_LEN:
        raise ValueError("Ziel ungültig: leer oder zu lang")
    if not (target.startswith("http://") or target.startswith("https://")):
        raise ValueError("Ziel ungültig: nur http:// oder https://")
    if any(ch.isspace() or ord(ch) < 0x20 or ord(ch) == 0x7F for ch in target):
        raise ValueError("Ziel ungültig: keine Leerzeichen oder Steuerzeichen erlaubt")
    if "javascript:" in target.lower():
        raise ValueError("Ziel ungültig: javascript: ist nicht erlaubt")


def validate_note(note: str) -> None:
    if len(note) > _MAX_NOTE_LEN:
        raise ValueError("Notiz zu lang (höchstens 200 Zeichen)")


def validate_id(link_id: str) -> None:
    if not ID_RE.match(link_id):
        raise ValueError(
            "Ungültige Kurz-ID '%s' (erlaubt: A-Z 0-9 -, bis 16 Zeichen, beginnt mit A-Z 0-9)" % link_id
        )


class LinkStore:
    """SQLite-Speicher für Kurz-Links. Threadsicher über einen einzigen `threading.Lock`."""

    def __init__(self, db_path: str | Path):
        self._path = str(db_path)
        parent = Path(self._path).parent
        if str(parent) not in ("", "."):
            parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self._path, check_same_thread=False, timeout=5)
        with self._lock:
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS links ("
                "id TEXT PRIMARY KEY, target TEXT, note TEXT NOT NULL DEFAULT '', "
                "created TEXT NOT NULL, updated TEXT NOT NULL, hits INTEGER NOT NULL DEFAULT 0)"
            )
            self._conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @staticmethod
    def _row_to_dict(row: tuple) -> dict[str, Any]:
        link_id, target, note, created, updated, hits = row
        return {
            "id": link_id,
            "target": target,
            "note": note,
            "created": created,
            "updated": updated,
            "hits": hits,
        }

    def get(self, link_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT id, target, note, created, updated, hits FROM links WHERE id = ?", (link_id,)
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def exists(self, link_id: str) -> bool:
        with self._lock:
            row = self._conn.execute("SELECT 1 FROM links WHERE id = ?", (link_id,)).fetchone()
        return row is not None

    def create(self, link_id: str, target: str | None, note: str, *, now: str) -> dict[str, Any]:
        with self._lock:
            self._conn.execute(
                "INSERT INTO links (id, target, note, created, updated, hits) VALUES (?, ?, ?, ?, ?, 0)",
                (link_id, target, note, now, now),
            )
            self._conn.commit()
        return self.get(link_id)  # type: ignore[return-value]

    def upsert(
        self, link_id: str, target: str | None, note: str | None, *, now: str, note_provided: bool
    ) -> tuple[dict[str, Any], bool]:
        with self._lock:
            row = self._conn.execute("SELECT note FROM links WHERE id = ?", (link_id,)).fetchone()
            if row is None:
                final_note = note if note_provided and note is not None else ""
                self._conn.execute(
                    "INSERT INTO links (id, target, note, created, updated, hits) VALUES (?, ?, ?, ?, ?, 0)",
                    (link_id, target, final_note, now, now),
                )
                created = True
            else:
                final_note = note if note_provided and note is not None else row[0]
                self._conn.execute(
                    "UPDATE links SET target = ?, note = ?, updated = ? WHERE id = ?",
                    (target, final_note, now, link_id),
                )
                created = False
            self._conn.commit()
        return self.get(link_id), created  # type: ignore[return-value]

    def delete(self, link_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM links WHERE id = ?", (link_id,))
            self._conn.commit()
        return cur.rowcount > 0

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, target, note, created, updated, hits FROM links ORDER BY id"
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def hit(self, link_id: str) -> None:
        with self._lock:
            self._conn.execute("UPDATE links SET hits = hits + 1 WHERE id = ?", (link_id,))
            self._conn.commit()

    def count(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) FROM links").fetchone()
        return row[0]

    def next_auto_id(self) -> str:
        with self._lock:
            row = self._conn.execute("SELECT value FROM meta WHERE key = 'counter'").fetchone()
            counter = int(row[0]) if row else 0
            while True:
                counter += 1
                candidate = _to_base36(counter)
                exists = self._conn.execute(
                    "SELECT 1 FROM links WHERE id = ?", (candidate,)
                ).fetchone()
                if exists is None:
                    break
            self._conn.execute(
                "INSERT INTO meta (key, value) VALUES ('counter', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (str(counter),),
            )
            self._conn.commit()
        return candidate


def _hint_html(link_id: str) -> str:
    return (
        "<!doctype html><html lang=\"de\"><head><meta charset=\"utf-8\">"
        f"<title>Kurz-Link {link_id}</title></head><body>"
        f"<p>Für {link_id} ist noch kein Ziel hinterlegt.</p></body></html>"
    )


def _not_found_html() -> HTMLResponse:
    return HTMLResponse(
        "<!doctype html><html lang=\"de\"><head><meta charset=\"utf-8\">"
        "<title>Kurz-Link</title></head><body><p>Unbekannter Kurz-Link</p></body></html>",
        status_code=404,
    )


class AdminAuthError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message


def create_app(
    db_path: str | Path, admin_token: str | None, *, clock: Callable[[], datetime] | None = None
) -> FastAPI:
    clock = clock or (lambda: datetime.now(timezone.utc))
    store = LinkStore(db_path)

    app = FastAPI(title="Kurz-Link-Dienst", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store = store

    def get_store() -> LinkStore:
        return app.state.store

    def require_admin(authorization: str | None = Header(default=None)) -> None:
        if not admin_token or len(admin_token) < _MIN_ADMIN_TOKEN_LEN:
            raise AdminAuthError(503, "Admin-Token nicht gesetzt")
        given = None
        if authorization and authorization.startswith("Bearer "):
            given = authorization[len("Bearer "):]
        if given is None or not hmac.compare_digest(given, admin_token):
            raise AdminAuthError(401, "Nicht angemeldet")

    @app.exception_handler(AdminAuthError)
    async def _admin_auth_handler(request: Request, exc: AdminAuthError) -> JSONResponse:
        return JSONResponse({"error": exc.message}, status_code=exc.status_code)

    @app.middleware("http")
    async def _security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    # --- öffentlich: Health und Redirect --------------------------------------

    @app.get("/health")
    def health() -> JSONResponse:
        try:
            n = store.count()
        except sqlite3.Error:
            return JSONResponse({"ok": False, "error": "Datenbank nicht lesbar"}, status_code=503)
        return JSONResponse({"ok": True, "links": n, "version": "1"})

    # --- Admin-API -------------------------------------------------------------

    @app.post("/api/links", status_code=201, dependencies=[Depends(require_admin)])
    def create_link(body: LinkCreate) -> JSONResponse:
        if body.id is not None:
            try:
                validate_id(body.id)
            except ValueError as exc:
                raise HTTPException(422, detail=str(exc)) from exc
            link_id = body.id
            if store.exists(link_id):
                raise HTTPException(409, detail=f"Kurz-ID '{link_id}' ist bereits vergeben")
        else:
            link_id = store.next_auto_id()

        if body.target is not None:
            try:
                validate_target(body.target)
            except ValueError as exc:
                raise HTTPException(422, detail=str(exc)) from exc
        try:
            validate_note(body.note)
        except ValueError as exc:
            raise HTTPException(422, detail=str(exc)) from exc

        now = _iso(clock())
        link = store.create(link_id, body.target, body.note, now=now)
        logger.info("Admin-Änderung: %s angelegt", link_id)
        return JSONResponse(link, status_code=201)

    @app.put("/api/links/{link_id}", dependencies=[Depends(require_admin)])
    def put_link(link_id: str, body: LinkUpdate) -> JSONResponse:
        try:
            validate_id(link_id)
        except ValueError as exc:
            raise HTTPException(422, detail=str(exc)) from exc
        if "target" not in body.model_fields_set:
            raise HTTPException(422, detail="'target' fehlt")
        if body.target is not None:
            try:
                validate_target(body.target)
            except ValueError as exc:
                raise HTTPException(422, detail=str(exc)) from exc
        note_provided = "note" in body.model_fields_set
        if note_provided and body.note is not None:
            try:
                validate_note(body.note)
            except ValueError as exc:
                raise HTTPException(422, detail=str(exc)) from exc

        now = _iso(clock())
        link, created = store.upsert(link_id, body.target, body.note, now=now, note_provided=note_provided)
        logger.info("Admin-Änderung: %s %s", link_id, "angelegt" if created else "aktualisiert")
        return JSONResponse(link, status_code=201 if created else 200)

    @app.get("/api/links", dependencies=[Depends(require_admin)])
    def list_links() -> JSONResponse:
        return JSONResponse({"links": store.list()})

    @app.get("/api/links/{link_id}", dependencies=[Depends(require_admin)])
    def get_link(link_id: str) -> JSONResponse:
        link = store.get(link_id)
        if link is None:
            raise HTTPException(404, detail="Unbekannte Kurz-ID")
        return JSONResponse(link)

    @app.delete("/api/links/{link_id}", status_code=204, dependencies=[Depends(require_admin)])
    def delete_link(link_id: str):
        if not store.delete(link_id):
            raise HTTPException(404, detail="Unbekannte Kurz-ID")
        logger.info("Admin-Änderung: %s gelöscht", link_id)
        return None

    # --- öffentlicher Redirect (zuletzt registriert: Einzelsegment-Catch-all) --

    @app.get("/")
    def root() -> HTMLResponse:
        return _not_found_html()

    @app.api_route("/{raw_id}", methods=["GET", "HEAD"])
    def redirect(raw_id: str, request: Request):
        link_id = raw_id.upper()
        if not ID_RE.match(link_id):
            return _not_found_html()
        link = store.get(link_id)
        if link is None:
            return _not_found_html()
        if link["target"] is None:
            return HTMLResponse(_hint_html(link_id))
        if request.method == "GET":
            store.hit(link_id)
        return RedirectResponse(
            link["target"],
            status_code=302,
            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
        )

    return app


def factory() -> FastAPI:
    """Fabrikfunktion für uvicorn: `uvicorn shortlink:factory --factory`.

    Liest die Umgebungsvariablen erst hier, nicht beim Modul-Import, damit ein
    bloßer Import (z. B. in Tests) keine Datei unter `/data` anlegt.
    """
    db_path = os.environ.get("SHORTLINK_DB", "/data/shortlink.sqlite3")
    admin_token = os.environ.get("SHORTLINK_ADMIN_TOKEN")
    return create_app(db_path, admin_token)
