"""Sprache je Anfrage für die Web-API (reine ASGI-Middleware, puffert keine SSE-Ströme).

Reihenfolge: Kopfzeile `X-Tapesmith-Language` (setzt die Web-Oberfläche mit ihrer aufgelösten
Sprache), Parameter `lang` (für Links, Bilder und den Ereignis-Strom, die keine Kopfzeilen senden
können), `Accept-Language`, sonst `i18n.default_language()` (`TAPESMITH_LANG`, `app.language`,
Windows-Anzeigesprache). Die Sprache gilt für `i18n._t`/`tr` während der ganzen Anfrage, auch in
Threadpool-Aufrufen der Routen (Kopie des Kontexts).
"""

from __future__ import annotations

from urllib.parse import parse_qs

from tapesmith import i18n

LANGUAGE_HEADER = b"x-tapesmith-language"
LANGUAGE_PARAM = "lang"


def scope_language(scope: dict) -> str | None:
    """Sprache einer Anfrage aus Kopfzeilen und Parametern oder None (dann gilt die Voreinstellung)."""
    accept = None
    for name, value in scope.get("headers") or ():
        if name == LANGUAGE_HEADER:
            found = i18n.normalize(value.decode("latin-1"))
            if found:
                return found
        elif name == b"accept-language":
            accept = value.decode("latin-1")
    query = scope.get("query_string") or b""
    if query:
        values = parse_qs(query.decode("latin-1")).get(LANGUAGE_PARAM)
        if values:
            found = i18n.normalize(values[0])
            if found:
                return found
    return i18n.parse_accept_language(accept)


class LanguageMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        token = i18n.set_language(scope_language(scope))
        try:
            await self.app(scope, receive, send)
        finally:
            i18n.reset_language(token)
