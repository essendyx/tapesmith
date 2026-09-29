"""HTTP-Client der Homelab-Integrationen mit einheitlicher Fehlerabbildung.

Alle Aufrufe laufen über `make_client` mit injizierbarem `transport` (Tests: `httpx.MockTransport`).
Header (und damit Tokens) erscheinen nie in Meldungen oder Logs.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from tapesmith.integrations.errors import AuthFailed, NotConfigured, NotReachable, UpstreamError
from tapesmith.i18n import _t

BODY_EXCERPT = 200


def _user_agent() -> str:
    try:
        from tapesmith import __version__
    except ImportError:
        return "tapesmith"
    return f"tapesmith/{__version__}"


def make_client(base_url: str, *, service: str, headers: Mapping[str, str] | None = None,
                timeout_s: float = 10.0, verify: bool = True,
                transport: httpx.BaseTransport | None = None) -> httpx.Client:
    """httpx-Client für einen Dienst: Basis-URL, Zeitlimit, TLS-Prüfung, keine Weiterleitungen.

    Ohne `base_url` (Dienst nicht eingetragen, Standard) entsteht ein Client, dessen erste Anfrage
    `NotConfigured` meldet; so bleiben Integrationen ohne Angaben einfach aus."""
    all_headers = {"User-Agent": _user_agent(), **dict(headers or {})}
    if not base_url:
        def not_configured(request: httpx.Request) -> httpx.Response:
            raise NotConfigured(service, _t("nicht eingerichtet: Adresse fehlt (Einstellungen, Homelab)"))

        return httpx.Client(base_url="http://nicht-eingerichtet.invalid", headers=all_headers,
                            transport=httpx.MockTransport(not_configured), follow_redirects=False)
    return httpx.Client(base_url=base_url, timeout=httpx.Timeout(timeout_s), verify=verify,
                        headers=all_headers, transport=transport, follow_redirects=False)


def _base(client: httpx.Client) -> str:
    return str(client.base_url).rstrip("/")


def _excerpt(response: httpx.Response) -> str:
    try:
        text = response.text
    except Exception:  # noqa: BLE001 (unlesbarer Körper)
        return ""
    return " ".join(text.split())[:BODY_EXCERPT]


def request_raw(client: httpx.Client, method: str, path: str, *, service: str,
                ok: tuple[int, ...] = (200,), **kw) -> httpx.Response:
    """Anfrage mit Fehlerabbildung; gibt die Antwort zurück, wenn ihr Status in `ok` liegt."""
    try:
        response = client.request(method, path, **kw)
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        raise NotReachable(service, _t("nicht erreichbar ({base})", base=_base(client)),
                           hint=_t("Adresse und Netz prüfen")) from exc
    status = response.status_code
    if status in ok:
        return response
    if status in (401, 403):
        raise AuthFailed(service, _t("Zugriff abgelehnt (HTTP {status})", status=status), hint=_t("Token und Rechte prüfen"))
    if status == 404:
        raise UpstreamError(service, _t("Nicht gefunden: {path}", path=path))
    excerpt = _excerpt(response)
    raise UpstreamError(service, f"HTTP {status}: {excerpt}" if excerpt else f"HTTP {status}")


def parse_json(response: httpx.Response, *, service: str) -> Any:
    """JSON-Körper der Antwort; 204 bzw. leerer Körper ergibt None, kein JSON `UpstreamError`."""
    if response.status_code == 204 or not response.content.strip():
        return None
    try:
        return response.json()
    except ValueError as exc:
        raise UpstreamError(service, _t("Antwort ist kein JSON")) from exc


def request_json(client: httpx.Client, method: str, path: str, *, service: str,
                 ok: tuple[int, ...] = (200, 201), **kw) -> Any:
    """Anfrage mit Fehlerabbildung, Rückgabe als JSON (204 bzw. leer: None)."""
    response = request_raw(client, method, path, service=service, ok=ok, **kw)
    return parse_json(response, service=service)
