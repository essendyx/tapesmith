"""Zugriffsmodell der Web-API: Rollen, Principal, LAN-Freigabe.

Die Middleware (`webapi.security`) legt je Anfrage einen `Principal` in
`scope["state"]["p12_principal"]` ab. Routen lesen ihn über `principal(request)` und die Quelle
eines Auftrags über `job_origin(request)`. Die Rollen-Tabelle ist eine Positivliste: was nicht
eingetragen ist, bleibt für `drucken` und `familie` gesperrt.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from fastapi import HTTPException, Request

from tapesmith import config as config_mod
from tapesmith import netinfo
from tapesmith.i18n import N_, _t

ROLE_ADMIN, ROLE_PRINT, ROLE_FAMILY = "admin", "drucken", "familie"
ROLES = (ROLE_ADMIN, ROLE_PRINT, ROLE_FAMILY)
FORBIDDEN_TEXT = N_("Keine Berechtigung für diese Aktion")
PRINCIPAL_KEY = "p12_principal"


@dataclass(frozen=True)
class Principal:
    kind: str            # "session" | "token" | "none"
    role: str | None     # None nur bei kind "none" (ungeschützte Pfade)
    client: str          # Client-Adresse
    loopback: bool
    token_id: str | None = None
    token_name: str | None = None
    origin: str = "gui"  # JobMeta.source für Aufträge dieser Anfrage


NO_PRINCIPAL = Principal("none", None, "", False)


def _rules(entries: Sequence[tuple[str, str]]) -> list[tuple[str, re.Pattern]]:
    return [(method, re.compile(pattern)) for method, pattern in entries]


FAMILY_RULES = _rules([
    ("GET", r"^/api/v1/familie/(vorlagen|status)$"),
    ("POST", r"^/api/v1/familie/(vorschau|drucken)$"),
])

PRINT_RULES = _rules([
    ("GET", r"^/api/v1/(app|status|events|queue|jobs|docs|openapi\.json|preview\.png)$"),
    ("POST", r"^/api/v1/status/refresh$"),
    ("POST", r"^/api/v1/print(/text|/cancel|/continue)?$"),
    ("DELETE", r"^/api/v1/jobs/\d+$"),
    ("POST", r"^/api/v1/labels/(render|print)$"),
    ("GET", r"^/api/v1/labels/(fonts|recent-texts)$"),
    ("GET", r"^/api/v1/templates$"),
    ("GET", r"^/api/v1/templates/[A-Za-z0-9_-]+$"),
    ("GET", r"^/api/v1/gallery(/.*)?$"),
    ("POST", r"^/api/v1/batch/(table|plan|print)$"),
    ("GET", r"^/api/v1/history(/\d+(/thumb\.png)?)?$"),
    ("*", r"^/mcp(/.*)?$"),
])

ROLE_RULES: dict[str, list[tuple[str, re.Pattern]]] = {
    ROLE_FAMILY: FAMILY_RULES,
    ROLE_PRINT: FAMILY_RULES + PRINT_RULES,
}


def _matches(rules: Sequence[tuple[str, re.Pattern]], method: str, path: str) -> bool:
    for rule_method, pattern in rules:
        if (rule_method == "*" or rule_method == method) and pattern.fullmatch(path):
            return True
    return False


def allowed(role: str, method: str, path: str) -> bool:
    """Darf `role` die Anfrage `method path` stellen? `admin` immer, unbekannte Rolle nie."""
    if role == ROLE_ADMIN:
        return True
    rules = ROLE_RULES.get(role)
    if rules is None:
        return False
    return _matches(rules, str(method).upper(), path)


def is_loopback(host: str | None) -> bool:
    """`127.0.0.1`, `::1` und alles, was mit `127.` beginnt (auch IPv4-gemappt)."""
    if not host:
        return False
    if host.lower().startswith("::ffff:"):
        host = host[7:]
    return host == "::1" or host.startswith("127.")


@dataclass(frozen=True)
class LanPolicy:
    enabled: bool
    networks: tuple[str, ...]
    hosts: frozenset[str]       # Hostnamen/Adressen ohne Port, klein geschrieben

    @classmethod
    def from_config(cls, cfg: dict, *, addresses: Sequence[str] | None = None,
                    hostname: str | None = None) -> LanPolicy:
        enabled = bool(config_mod.setting(cfg, "lan.enabled"))
        networks = tuple(str(n) for n in config_mod.setting(cfg, "lan.allowed_networks") or ())
        name = hostname if hostname is not None else netinfo.host_name()
        hosts: set[str] = {ip.lower() for ip in netinfo.lan_addresses(cfg, addresses)}
        if name:
            hosts.update({name.lower(), f"{name.lower()}.local"})
        hosts.update(str(h).lower() for h in config_mod.setting(cfg, "lan.hostnames") or ())
        return cls(enabled=enabled, networks=networks, hosts=frozenset(hosts))

    @classmethod
    def disabled(cls) -> LanPolicy:
        return cls(enabled=False, networks=(), hosts=frozenset())

    def admits(self, client: str | None) -> bool:
        """Darf ein Nicht-Loopback-Client überhaupt zugreifen?"""
        return bool(self.enabled and client and netinfo.in_networks(client, self.networks))


def principal(request: Request) -> Principal:
    state = request.scope.get("state") or {}
    found = state.get(PRINCIPAL_KEY) if isinstance(state, dict) else None
    return found if isinstance(found, Principal) else NO_PRINCIPAL


def job_origin(request: Request) -> str:
    return principal(request).origin


def require_role(*roles: str) -> Callable:
    """FastAPI-Dependency: 403, wenn die Rolle des Principals nicht in `roles` liegt."""
    wanted = frozenset(roles)

    def dependency(request: Request) -> Principal:
        found = principal(request)
        if found.role not in wanted:
            raise HTTPException(status_code=403, detail=_t(FORBIDDEN_TEXT))
        return found

    return dependency
