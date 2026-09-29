"""Routenabgleich PowerShell-Modul gegen die App und Rollen-Tabelle je Route.

1. Jeder `'/api/v1/…'`-Pfad aus `deploy/powershell/Tapesmith/Tapesmith.psm1` existiert in
   `create_app(ctx).routes` mit der verwendeten Methode, und die Rolle `drucken` darf ihn laut
   `access.allowed` (sonst könnte ein Drucken-Token das Modul nicht nutzen).
2. Rollen-Tabelle: jede Route aus `routes_short`, `routes_family` und `/mcp` ist für die
   festgelegten Rollen erlaubt, jede Route aus `routes_access` nur für `admin`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from starlette.routing import Match

from tapesmith.webapi import access, routes_access, routes_family, routes_short
from tapesmith.webapi.app import API_PREFIX, create_app
from webapi_fakes import close_ctx, make_ctx

REPO_ROOT = Path(__file__).resolve().parent.parent
PSM1 = REPO_ROOT / "deploy" / "powershell" / "Tapesmith" / "Tapesmith.psm1"

_PATH_RE = re.compile(r"""['"](/api/v1/[^'"\s]*)['"]""")
_METHOD_RE = re.compile(r"-Method\s+'([A-Z]+)'")
# Parameterteile im PowerShell-Pfad durch Beispielwerte ersetzen
_PARAM_SUBST = [
    (re.compile(r"\$\(\[uri\]::EscapeDataString\(\$\w+\)\)"), "gefriergut"),
    (re.compile(r"\$Id\b"), "7"),
]
CATCH_ALL = {"/api/{rest:path}", "/{path:path}", "/mcp/{rest:path}"}


@pytest.fixture
def app(tmp_path):
    ctx = make_ctx(tmp_path)
    try:
        yield create_app(ctx)
    finally:
        close_ctx(ctx)


def _ps_calls() -> list[tuple[str, str, int]]:
    """(Methode, Pfad mit Beispielwerten, Zeilennummer) je Pfad-Literal außerhalb von Kommentaren."""
    lines = PSM1.read_text(encoding="utf-8-sig").splitlines()
    calls = []
    for index, line in enumerate(lines):
        if line.lstrip().startswith("#"):
            continue
        for match in _PATH_RE.finditer(line):
            method = None
            for probe in lines[index:index + 4]:   # -Method steht in derselben oder einer der nächsten Zeilen
                found = _METHOD_RE.search(probe)
                if found:
                    method = found.group(1)
                    break
            assert method is not None, f"Tapesmith.psm1:{index + 1}: keine -Method zu {match.group(1)}"
            path = match.group(1)
            for pattern, value in _PARAM_SUBST:
                path = pattern.sub(value, path)
            assert "$" not in path, f"Tapesmith.psm1:{index + 1}: unbekannter Parameter in {path}"
            calls.append((method, path, index + 1))
    return calls


def _matching_route(app, method: str, path: str):
    scope = {"type": "http", "method": method, "path": path, "root_path": "", "query_string": b"",
             "headers": []}
    for route in app.routes:
        if getattr(route, "path", None) in CATCH_ALL:
            continue
        match, _child = route.matches(scope)
        if match == Match.FULL:
            return route
    return None


def test_ps_module_paths_found():
    calls = _ps_calls()
    found = {(m, p) for m, p, _ in calls}
    assert ("GET", "/api/v1/status") in found
    assert ("POST", "/api/v1/print") in found
    assert ("POST", "/api/v1/print/text") in found
    assert ("DELETE", "/api/v1/jobs/7") in found
    assert len(calls) >= 7


def test_ps_module_routes_exist_and_allowed_for_print_role(app):
    for method, path, line in _ps_calls():
        route = _matching_route(app, method, path)
        assert route is not None, f"Tapesmith.psm1:{line}: {method} {path} fehlt in der App"
        assert access.allowed("drucken", method, path), f"Tapesmith.psm1:{line}: {method} {path} für drucken gesperrt"
        assert not access.allowed("familie", method, path), f"{method} {path} darf nicht für familie offen sein"


# ---------------------------------------------------------------- Rollen-Tabelle je Route


def _example_path(route_path: str) -> str:
    """Pfadparameter durch Beispielwerte ersetzen (`{id}` usw. als Zahl, sonst Text)."""
    def value(match: re.Match) -> str:
        name = match.group(1).split(":")[0]
        return "7" if name in {"id", "job_id", "entry_id"} else "beispiel"
    return re.sub(r"\{([^}]+)\}", value, route_path)


def _router_routes(module) -> list[tuple[str, str]]:
    result = []
    for route in module.router.routes:
        for method in sorted(route.methods - {"HEAD"}):
            result.append((method, API_PREFIX + route.path))
    assert result, module.__name__
    return result


# Routen, deren erlaubte Rollen vom Standard ihres Moduls abweichen (explizite Ausnahmen)
EXCEPTIONS: dict[tuple[str, str], set[str]] = {}

EXPECTED = [
    (routes_short, {"admin", "drucken"}),
    (routes_family, {"admin", "drucken", "familie"}),
    (routes_access, {"admin"}),
]


@pytest.mark.parametrize("module,roles", EXPECTED, ids=lambda x: getattr(x, "__name__", ""))
def test_role_table_per_router(module, roles):
    for method, route_path in _router_routes(module):
        path = _example_path(route_path)
        wanted = EXCEPTIONS.get((method, route_path), roles)
        got = {role for role in access.ROLES if access.allowed(role, method, path)}
        assert got == wanted, f"{method} {route_path}: {sorted(got)} statt {sorted(wanted)}"


def test_role_table_mcp():
    for method in ("POST", "GET", "DELETE"):
        for path in ("/mcp", "/mcp/x"):
            got = {role for role in access.ROLES if access.allowed(role, method, path)}
            assert got == {"admin", "drucken"}, (method, path, got)


def test_every_app_api_route_known_to_role_table(app):
    """Jede API-Route der App: `admin` darf alles, `familie` nur die Familienrouten."""
    family_paths = {API_PREFIX + r.path for r in routes_family.router.routes}
    for route in app.routes:
        path = getattr(route, "path", "")
        if path in CATCH_ALL or not path.startswith(API_PREFIX):
            continue
        for method in sorted(getattr(route, "methods", set()) - {"HEAD"}):
            example = _example_path(path)
            assert access.allowed("admin", method, example)
            assert access.allowed("familie", method, example) == (path in family_paths), (method, path)
