"""Sicherheitsschicht der Web-API als reine ASGI-Middleware.

Bewusst keine `BaseHTTPMiddleware`: die würde SSE-Ströme puffern. Reihenfolge je Anfrage:
1. Client-Adresse: Loopback immer; sonst nur mit aktiver LAN-Freigabe und Adresse in
   `lan.allowed_networks`, sonst 403.
2. Rate-Limit (nur Nicht-Loopback): gesperrte Adresse bekommt 429 mit `Retry-After`.
3. `Host` (DNS-Rebinding): Loopback `127.0.0.1:<port>`/`localhost:<port>`, LAN `<host>:<port>`
   mit `host` aus `LanPolicy.hosts`, sonst 403.
4. `Origin` muss `http://<Host>` sein, `Sec-Fetch-Site: cross-site` nie (CSRF), sonst 403.
5. Geschützte Pfade (`/api...`, `/mcp...`) brauchen ein Token: `Authorization: Bearer`, dann
   `X-P12-Token`, nur bei GET `?t=`. Sitzungs-Token nur für Loopback (Rolle admin), API-Tokens
   überall (Rolle aus dem Token). Sonst 401; ein gesetztes, falsches Token ist ein Fehlversuch.
6. Rollenprüfung über `access.allowed`, sonst 403.
Das Ergebnis liegt als `Principal` in `scope["state"]["p12_principal"]`, auch für ungeschützte
Pfade. Zusätzlich `Cache-Control: no-store` für `/api`, `/mcp` und `/health`, `nosniff`,
`no-referrer`, `DENY`. Klartext-Tokens erscheinen nie im Log. Alle Getter werden je Anfrage gelesen
(der Port steht erst nach dem Binden fest, Tests tauschen den Kontext).
"""

from __future__ import annotations

import hmac
import json
import logging
import math
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs

from tapesmith.webapi import access
from tapesmith.webapi.access import LanPolicy, Principal
from tapesmith.webapi.errors import error_json, http_error_body
from tapesmith.i18n import N_, _t

log = logging.getLogger(__name__)

TOKEN_HEADER = b"x-p12-token"
SOURCE_HEADER = b"x-p12-source"
# Ein Token/Aufrufer darf die Quelle eines Auftrags per Kopfzeile auf genau diese Werte setzen
# (keine freie Quelle): "hotfolder" fuer "tapesmith hotfolder run-once" (HttpPrinter), damit dessen
# Auftraege im Verlauf auch als Quelle "hotfolder" erscheinen statt als "api".
SWITCHABLE_SOURCES = ("api", "mcp", "hotfolder")
TEXT_ADDRESS = N_("Zugriff verweigert: Adresse nicht freigegeben")
TEXT_HOST = N_("Zugriff verweigert: unbekannter Host")
TEXT_ORIGIN = N_("Zugriff verweigert: fremde Herkunft")
TEXT_CROSS_SITE = N_("Zugriff verweigert: seitenübergreifende Anfrage")
TEXT_LOGIN = N_("Nicht angemeldet: Token fehlt oder ist falsch")
HINT_LOGIN_LOCAL = N_("Oberfläche über ‚tapesmith app‘ öffnen")
TEXT_LOCKED = N_("Zu viele Fehlversuche, bitte später erneut versuchen")
_COMMON_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
    (b"x-frame-options", b"DENY"),
]


def is_api_path(path: str) -> bool:
    return path == "/api" or path.startswith("/api/")


def is_mcp_path(path: str) -> bool:
    return path == "/mcp" or path.startswith("/mcp/")


FAMILY_PREFIX = "/api/v1/familie"


def is_family_path(path: str) -> bool:
    """Familienrouten (Quelle ist dort immer `api`)."""
    return path == FAMILY_PREFIX or path.startswith(FAMILY_PREFIX + "/")


def is_protected_path(path: str) -> bool:
    return is_api_path(path) or is_mcp_path(path)


def _header(scope, name: bytes) -> str | None:
    for key, value in scope.get("headers") or ():
        if key.lower() == name:
            return value.decode("latin-1")
    return None


def _same(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def _given_token(scope) -> str | None:
    auth = _header(scope, b"authorization")
    if auth is not None:
        parts = auth.strip().split(None, 1)
        if len(parts) == 2 and parts[0].lower() == "bearer" and parts[1].strip():
            return parts[1].strip()
    given = _header(scope, TOKEN_HEADER)
    if given is not None:
        return given
    if scope.get("method") == "GET":
        values = parse_qs(scope.get("query_string", b"").decode("latin-1")).get("t")
        if values:
            return values[0]
    return None


class _Reject(Exception):
    def __init__(self, status: int, body: dict, headers: list[tuple[bytes, bytes]] | None = None):
        super().__init__(status)
        self.status = status
        self.body = body
        self.headers = headers or []


def _reject(status: int, text: str, **kw) -> _Reject:
    return _Reject(status, http_error_body(status, text), **kw)


class SecurityMiddleware:
    def __init__(self, app, *, token_getter: Callable[[], str], port_getter: Callable[[], int],
                 tokens_getter: Callable[[], Any] = lambda: None,
                 lan_getter: Callable[[], LanPolicy | None] = lambda: None,
                 limiter_getter: Callable[[], Any] = lambda: None):
        self.app = app
        self._token_getter = token_getter
        self._port_getter = port_getter
        self._tokens_getter = tokens_getter
        self._lan_getter = lan_getter
        self._limiter_getter = limiter_getter

    # ------------------------------------------------------------------ Prüfungen

    def _check_host(self, scope, port: int, loopback: bool, lan: LanPolicy) -> str:
        host = (_header(scope, b"host") or "").lower()
        if loopback:
            if host not in {f"127.0.0.1:{port}", f"localhost:{port}"}:
                raise _reject(403, _t(TEXT_HOST))
            return host
        name, sep, host_port = host.rpartition(":")
        if not sep or host_port != str(port) or name not in lan.hosts:
            raise _reject(403, _t(TEXT_HOST))
        return host

    @staticmethod
    def _check_origin(scope, host: str, port: int, loopback: bool) -> None:
        origin = _header(scope, b"origin")
        if origin is not None:
            allowed = {f"http://{host}"}
            if loopback:
                allowed |= {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}
            if origin.lower() not in allowed:
                raise _reject(403, _t(TEXT_ORIGIN))
        fetch_site = _header(scope, b"sec-fetch-site")
        if fetch_site is not None and fetch_site.lower() == "cross-site":
            raise _reject(403, _t(TEXT_CROSS_SITE))

    def _verify_api_token(self, given: str):
        tokens = self._tokens_getter()
        if tokens is None:
            return None
        try:
            return tokens.verify(given)
        except Exception:  # noqa: BLE001 (defekte Token-Datei: niemand wird angemeldet)
            log.exception("API-Token konnte nicht geprüft werden")
            return None

    def _login(self, scope, client: str, loopback: bool, limiter) -> Principal:
        given = _given_token(scope)
        if given:
            session_token = self._token_getter()
            if loopback and session_token and _same(given, session_token):
                return Principal("session", access.ROLE_ADMIN, client, True, origin="gui")
            info = self._verify_api_token(given)
            if info is not None:
                if limiter is not None and not loopback:
                    limiter.success(client)
                return Principal("token", info.role, client, loopback, token_id=info.id,
                                 token_name=info.name, origin="api")
            log.warning("Fehlversuch von %s", client)
            if limiter is not None and not loopback:
                limiter.failure(client)
        if loopback:
            raise _Reject(401, error_json("Unauthorized", _t(TEXT_LOGIN), hint=_t(HINT_LOGIN_LOCAL)))
        raise _reject(401, _t(TEXT_LOGIN))

    @staticmethod
    def _with_origin(scope, found: Principal, path: str) -> Principal:
        origin = found.origin
        wanted = (_header(scope, SOURCE_HEADER) or "").strip().lower()
        if wanted in SWITCHABLE_SOURCES:
            origin = wanted
        if is_mcp_path(path):
            origin = "mcp"
        elif is_family_path(path):
            origin = "api"
        if origin == found.origin:
            return found
        return Principal(found.kind, found.role, found.client, found.loopback, token_id=found.token_id,
                         token_name=found.token_name, origin=origin)

    def _check(self, scope) -> Principal:
        client_info = scope.get("client")
        client = str(client_info[0]) if client_info else ""
        loopback = access.is_loopback(client)
        lan = self._lan_getter() or LanPolicy.disabled()
        if not loopback and not lan.admits(client):
            raise _reject(403, _t(TEXT_ADDRESS))
        limiter = self._limiter_getter()
        if not loopback and limiter is not None:
            remaining = limiter.blocked(client)
            if remaining > 0:
                # Toleranz gegen Rundung: (t + 900) - t kann knapp über 900 liegen
                seconds = str(max(1, math.ceil(remaining - 1e-6))).encode("ascii")
                raise _reject(429, _t(TEXT_LOCKED), headers=[(b"retry-after", seconds)])
        port = int(self._port_getter())
        host = self._check_host(scope, port, loopback, lan)
        self._check_origin(scope, host, port, loopback)
        path = scope.get("path", "")
        if not is_protected_path(path):
            return Principal("none", None, client, loopback)
        found = self._login(scope, client, loopback, limiter)
        if not access.allowed(found.role or "", scope.get("method", "GET"), path):
            raise _reject(403, access.FORBIDDEN_TEXT)
        return self._with_origin(scope, found, path)

    # ------------------------------------------------------------------ ASGI

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        no_store = is_protected_path(path) or path == "/health"

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = [(k, v) for k, v in message.get("headers", [])
                           if not (no_store and k.lower() == b"cache-control")]
                if no_store:
                    headers.append((b"cache-control", b"no-store"))
                existing = {k.lower() for k, _ in headers}
                headers.extend(h for h in _COMMON_HEADERS if h[0] not in existing)
                message = {**message, "headers": headers}
            await send(message)

        try:
            found = self._check(scope)
        except _Reject as rejected:
            body = json.dumps(rejected.body, ensure_ascii=False).encode("utf-8")
            await send_with_headers({"type": "http.response.start", "status": rejected.status,
                                     "headers": [(b"content-type", b"application/json"),
                                                 (b"content-length", str(len(body)).encode("ascii")),
                                                 *rejected.headers]})
            await send_with_headers({"type": "http.response.body", "body": body})
            return
        scope.setdefault("state", {})[access.PRINCIPAL_KEY] = found
        await self.app(scope, receive, send_with_headers)
