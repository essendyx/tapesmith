"""Client für den Kurz-Link-Dienst (eigenständiger Redirect-Dienst, siehe `deploy/shortlink`).

API: `POST /api/links`, `PUT/GET/DELETE /api/links/{id}`, `GET /api/links`; Anmeldung mit
`Authorization: Bearer <token>`. Kurz-URLs werden in Großbuchstaben gebaut, damit der QR-Code im
Alphanumerik-Modus klein bleibt.
"""

from __future__ import annotations

import builtins
import re
from dataclasses import dataclass

import httpx

from tapesmith.integrations.credentials import read_secret
from tapesmith.integrations.errors import NotConfigured, UpstreamError
from tapesmith.integrations.httpclient import make_client, parse_json, request_json, request_raw
from tapesmith.i18n import N_, _t

SERVICE = N_("Kurz-Link-Dienst")
ID_RE = re.compile(r"^[0-9A-Z][0-9A-Z-]{0,15}$")
_TARGET_RE = re.compile(r"^https?://\S+$")


@dataclass(frozen=True)
class ShortLink:
    id: str
    target: str | None
    note: str
    created: str
    updated: str
    hits: int


def normalize_id(raw: str) -> str:
    """Kurz-ID bereinigen (strip, Großbuchstaben) und prüfen."""
    value = str(raw).strip().upper()
    if not ID_RE.match(value):
        raise ValueError(_t("Ungültige Kurz-ID '{raw}' (erlaubt: A-Z 0-9 -, bis 16 Zeichen)", raw=raw))
    return value


def short_url(base_url: str, link_id: str) -> str:
    """Kurz-URL in Großbuchstaben, z. B. `HTTPS://L.EXAMPLE.COM/HL-0042`."""
    return base_url.rstrip("/").upper() + "/" + normalize_id(link_id)


def _check_target(target: str | None) -> str | None:
    if target is None:
        return None
    if not isinstance(target, str) or not _TARGET_RE.match(target):
        raise ValueError(_t("Ungültiges Ziel '{target}' (erwartet http:// oder https:// ohne Leerzeichen)", target=target))
    return target


def _link(obj) -> ShortLink:
    try:
        return ShortLink(id=str(obj["id"]), target=obj.get("target"), note=obj.get("note") or "",
                         created=str(obj.get("created") or ""), updated=str(obj.get("updated") or ""),
                         hits=int(obj.get("hits") or 0))
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise UpstreamError(_t(SERVICE), _t("Antwort unvollständig (Link ohne id)")) from exc


class ShortlinkClient:
    """Verwaltung der Kurz-Links über die Admin-API des Dienstes."""

    def __init__(self, admin_url: str, token: str, *, timeout_s: float = 10.0,
                 transport: httpx.BaseTransport | None = None):
        self.admin_url = admin_url
        self._client = make_client(admin_url, service=_t(SERVICE),
                                   headers={"Authorization": f"Bearer {token}"},
                                   timeout_s=timeout_s, transport=transport)

    @classmethod
    def from_settings(cls, data: dict, *, keyring_module=None, environ=None,
                      transport=None) -> ShortlinkClient:
        """Client aus `homelab.json`: admin_url, sonst base_url; Token über `token_ref`."""
        section = data["shortlink"]
        admin_url = section.get("admin_url") or section.get("base_url")
        if not admin_url:
            raise NotConfigured(_t(SERVICE), _t("nicht eingerichtet: shortlink.base_url fehlt"),
                                hint=_t("In homelab.json 'shortlink.base_url' eintragen"))
        token = read_secret(section.get("token_ref"), what=_t(SERVICE), keyring_module=keyring_module,
                            environ=environ)
        return cls(admin_url, token, timeout_s=float(section.get("timeout_s") or 10.0), transport=transport)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> ShortlinkClient:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def create(self, target: str | None, *, link_id: str | None = None, note: str = "") -> ShortLink:
        """Legt einen Link an (409 bei vorhandener ID ergibt `UpstreamError`)."""
        body: dict = {"target": _check_target(target)}
        if link_id is not None:
            body["id"] = normalize_id(link_id)
        if note:
            body["note"] = note
        return _link(request_json(self._client, "POST", "/api/links", service=_t(SERVICE), json=body))

    def upsert(self, link_id: str, target: str | None, note: str = "") -> ShortLink:
        """Setzt das Ziel eines Links; legt ihn an, falls er fehlt (PUT)."""
        link_id = normalize_id(link_id)
        body = {"target": _check_target(target), "note": note}
        return _link(request_json(self._client, "PUT", f"/api/links/{link_id}", service=_t(SERVICE), json=body))

    def get(self, link_id: str) -> ShortLink | None:
        """Link oder None, wenn es ihn nicht gibt."""
        link_id = normalize_id(link_id)
        response = request_raw(self._client, "GET", f"/api/links/{link_id}", service=_t(SERVICE), ok=(200, 404))
        if response.status_code == 404:
            return None
        return _link(parse_json(response, service=_t(SERVICE)))

    def list(self) -> builtins.list[ShortLink]:
        """Alle Links."""
        data = request_json(self._client, "GET", "/api/links", service=_t(SERVICE))
        if not isinstance(data, dict) or not isinstance(data.get("links"), builtins.list):
            raise UpstreamError(_t(SERVICE), _t("Antwort unvollständig (links fehlt)"))
        return [_link(item) for item in data["links"]]

    def delete(self, link_id: str) -> bool:
        """Löscht einen Link; False, wenn es ihn nicht gab."""
        link_id = normalize_id(link_id)
        response = request_raw(self._client, "DELETE", f"/api/links/{link_id}", service=_t(SERVICE),
                               ok=(200, 204, 404))
        return response.status_code != 404


def configured(data: dict) -> bool:
    """Ob der Kurz-Link-Dienst eingerichtet ist (`shortlink.base_url` gesetzt)."""
    return bool(data.get("shortlink", {}).get("base_url"))


def link_for(data: dict, link_id: str, target: str | None, *, note: str = "", sync: bool = True,
             client: ShortlinkClient | None = None, keyring_module=None, environ=None,
             transport=None) -> str:
    """Inhalt für einen QR-Code: Kurz-URL (Dienst eingerichtet) oder `target`.

    `sync=False` (Vorschau, Trockenlauf, Label-Abruf): nur die Kurz-URL ausrechnen, ohne Netz und
    ohne Token. `sync=True` (echter Druck, Zieländerung): Link im Dienst setzen. Ohne lokales Ziel
    (`target=None`) wird ein vorhandener Link nie überschrieben, nur ein fehlender angelegt, damit ein
    per `p12 kurz set` gesetztes Ziel erhalten bleibt.
    """
    if not configured(data):
        if target is None:
            raise NotConfigured(_t(SERVICE), _t("nicht eingerichtet: shortlink.base_url fehlt"),
                                hint=_t("In homelab.json 'shortlink.base_url' eintragen"))
        return target
    url = short_url(data["shortlink"]["base_url"], link_id)
    if not sync:
        return url
    own = client is None
    if own:
        client = ShortlinkClient.from_settings(data, keyring_module=keyring_module, environ=environ,
                                               transport=transport)
    try:
        if target is not None or client.get(link_id) is None:
            client.upsert(link_id, target, note)
    finally:
        if own:
            client.close()
    return url
