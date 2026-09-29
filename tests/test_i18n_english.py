"""Englisch durchgängig: API-Antworten, mitgelieferte Vorlagen und CLI-Hilfe ohne deutsche Reste.

Die Prüfung sucht in allen nutzersichtbaren Texten nach Umlauten und typisch deutschen Wörtern.
Ausgenommen sind Werte, die Kennungen oder Nutzerdaten sind (Schlüssel wie `id`, `name`, `state`,
Vorlagen-IDs, Server-Statuswerte) und wenige Eigennamen (`ALLOWED`).
"""

from __future__ import annotations

import argparse
import io
import json
import re
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime

import pytest

from tapesmith import cli, i18n
from tapesmith.cli_cmds.base import discover_commands
from tapesmith.templates.store import builtin_templates
from webapi_fakes import close_ctx, make_client

EN = {"X-Tapesmith-Language": "en"}

GERMAN_WORDS = (
    "nicht", "und", "oder", "der", "die", "das", "ist", "sind", "wird", "werden", "mit", "für", "auf", "bei",
    "bitte", "kein", "keine", "keinen", "Drucker", "Vorlage", "Vorlagen", "Etikett", "Etiketten", "Fehler",
    "Einstellungen", "Warteschlange", "Verbindung", "verfügbar", "erreichbar", "Akku", "Deckel", "Seriennummer",
    "zuletzt", "gedruckt", "drucken", "Druck", "Feld", "Felder", "Wert", "muss", "darf", "unbekannt",
    "ungültig", "fehlt", "Datei", "Ordner", "Zeile", "Zeilen", "Länge", "Breite", "Schrift", "Band",
    "Beispiel", "Inhalt", "Gerät", "Raum", "Datum", "Haushalt", "Büro", "Kabel", "Netzteil", "Ziel",
    "Quelle", "Nummer", "Bezeichnung", "Eigentum", "Garantie", "Wartung", "Rückfrage", "Vorschau",
    "verbunden", "getrennt", "belegt", "Aufträge", "Auftrag", "Sicherung", "Oberfläche", "Kategorie",
)
GERMAN_RE = re.compile(r"(?<![A-Za-zÄÖÜäöüß])(" + "|".join(GERMAN_WORDS) + r")(?![A-Za-zÄÖÜäöüß])")
UMLAUT_RE = re.compile(r"[äöüÄÖÜß]")

# Eigennamen und Kennungen, die in englischen Texten stehen dürfen.
ALLOWED = re.compile(r"Deutsch|Installieren\.cmd|tapesmith-bericht|Garantie bis|Kaufdatum|Garantie Monate|"
                     r"Anhänge/Labels|Kurz-Link-Dienst|Seriennummer=sn|kabel\.tia_pattern|/verlauf|"
                     r"'dunkel'|'hell'|--rolle drucken|\(roles admin, drucken, familie\)|datentraeger|"
                     r"template 'datentraeger'|'reserviert'|--frei|schema, frei|ka neu|"
                     # Optionsnamen und Auswahlwerte der CLI sind Kennungen (bleiben deutsch)
                     r"verfügbar,reserviert,verkauft|--rolle|admin,drucken,familie|--kein-vermerk|--vermerk")

# Schlüssel, deren Werte Kennungen oder Daten sind (keine übersetzten Texte).
DATA_KEYS = {
    "id", "name", "key", "code", "kind", "state", "status", "source", "template", "type", "value", "values",
    "default", "choices", "sample", "path", "config_path", "templates_dir", "role", "roles", "tags",
    "unit", "visibility", "module", "icon", "definition", "input_fields_values", "keywords", "raw",
    "transport", "font", "fonts", "tape", "tapes", "target", "category_id", "language", "resolved_language",
    "system_language", "theme", "modules", "favorites", "recent", "home_key", "version", "accent", "profile",
    "material", "code_mode", "history_id", "job_key", "title_key", "entries", "categories",
}


def german_leaks(node, path: str = "") -> list[str]:
    """Pfade mit deutsch aussehenden Texten in einer JSON-Struktur."""
    leaks: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key in DATA_KEYS:
                continue
            leaks += german_leaks(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            leaks += german_leaks(value, f"{path}[{index}]")
    elif isinstance(node, str):
        text = ALLOWED.sub("", node)
        if UMLAUT_RE.search(text) or GERMAN_RE.search(text):
            leaks.append(f"{path}: {node[:120]!r}")
    return leaks


def text_leaks(text: str) -> list[str]:
    cleaned = ALLOWED.sub("", text)
    return [line for line in cleaned.splitlines() if UMLAUT_RE.search(line) or GERMAN_RE.search(line)]


def test_erkennung_selbst():
    assert german_leaks({"message": "Drucker nicht erreichbar"})
    assert german_leaks({"a": ["ok", {"b": "Größe"}]})
    assert not german_leaks({"message": "Printer unreachable", "state": "verbunden"})
    assert not german_leaks({"label": "Language: Deutsch"})


@pytest.fixture
def api(tmp_path):
    client, ctx = make_client(tmp_path)
    yield client, ctx
    close_ctx(ctx)


# ---------- API ----------

# GET-Routen ohne Pfadparameter, die JSON liefern (Ereignis-Strom, Downloads und Seiten ausgenommen).
SKIP_GET = {"/api/v1/events", "/api/v1/docs", "/api/v1/openapi.json", "/api/v1/support/report",
            "/api/v1/backup/download", "/api/v1/mcp"}


def _get_routes(client) -> list[str]:
    schema = client.get("/api/v1/openapi.json").json()
    routes = []
    for path, ops in schema["paths"].items():
        if "get" in ops and path.startswith("/api/v1/") and "{" not in path and path not in SKIP_GET:
            routes.append(path)
    return sorted(set(routes))


def test_get_routen_englisch(api):
    client, _ = api
    routes = _get_routes(client)
    assert len(routes) > 20
    leaks = []
    for path in routes:
        r = client.get(path, headers=EN)
        if "application/json" not in r.headers.get("content-type", ""):
            continue
        leaks += [f"{path} {leak}" for leak in german_leaks(r.json())]
    assert leaks == []


def test_status_und_app_englisch(api):
    client, ctx = api
    body = client.post("/api/v1/status/refresh", json={"quick": True}, headers=EN).json()
    assert german_leaks(body["view"]) == []
    assert "Connection:" in body["view"]["detail"]
    app = client.get("/api/v1/app", headers=EN).json()
    assert app["resolved_language"] == "de"      # Dienst: Systemsprache der Tests
    assert client.get("/api/v1/status", headers={"Accept-Language": "en-US,en;q=0.9"}).json()["view"]["detail"] \
        .startswith("Connection:")
    assert client.get("/api/v1/status").json()["view"]["detail"].startswith("Verbindung:")


def test_fehlerantworten_englisch(api):
    client, _ = api
    r = client.post("/api/v1/status/refresh", json={"quick": "ja"}, headers=EN)
    assert r.status_code == 422
    assert r.json()["error"]["message"] == "Invalid request: field ‚quick‘ must be true or false"
    r = client.get("/api/v1/templates/does-not-exist", headers=EN)
    assert r.status_code == 404
    assert german_leaks(r.json()) == []
    r = client.get("/api/v1/app", headers={"X-P12-Token": "falsch", **EN})
    assert r.status_code == 401
    assert r.json()["error"]["message"] == "Not signed in: token missing or wrong"


def test_vorschau_warnungen_englisch(api):
    client, _ = api
    long_text = {"kind": "text", "lines": ["x" * 400]}
    body = client.post("/api/v1/labels/render", json={"source": long_text}, headers=EN).json()
    assert german_leaks(body) == []
    body = client.post("/api/v1/labels/render", json={"source": {"kind": "text", "lines": []}}, headers=EN).json()
    assert german_leaks(body) == []


def test_parameter_lang_fuer_bilder_und_stroeme(api):
    client, _ = api
    body = client.get("/api/v1/status?lang=en").json()
    assert body["view"]["detail"].startswith("Connection:")


def test_vorlagen_api_englisch(api):
    client, _ = api
    names = [t["name"] for t in client.get("/api/v1/templates", headers=EN).json()["templates"]]
    assert "gefriergut" in names       # IDs bleiben
    leaks = []
    for name in names:
        body = client.get(f"/api/v1/templates/{name}", headers=EN).json()
        body.pop("definition", None)
        leaks += [f"{name} {leak}" for leak in german_leaks(body)]
    assert leaks == []
    detail = client.get("/api/v1/templates/gefriergut", headers=EN).json()
    assert detail["title"] == "freezer"
    assert detail["category"] == "Household"
    fields = {f["id"]: f for f in detail["fields"]}
    assert fields["kategorie"]["choices"][0] == "Meat"
    assert fields["inhalt"]["label"] == "Contents"
    de = client.get("/api/v1/templates/gefriergut").json()
    assert de["title"] == "gefriergut" and de["category"] == "Haushalt"


# ---------- Vorlagen ----------

def _template_texts(t) -> dict:
    """Nutzersichtbare Texte einer Vorlage (ohne Kennungen)."""
    data = {"title": t.display_title, "description": t.description, "category": t.category,
            "tags": list(t.tags), "fields": [], "sample": dict(t.sample)}
    for f in t.fields:
        data["fields"].append({"label": f.label, "choice_labels": [f.choice_label(c) for c in f.choices],
                               "default_text": f.default})
    if t.layout.get("lines"):
        data["lines"] = [re.sub(r"\{[^}]*\}", "", line) for line in t.layout["lines"]]
    if t.document is not None:
        data["texts"] = [re.sub(r"\{[^}]*\}", "", getattr(o, "text", "")) for o in t.document.objects]
    return data


# Kennungen und Werte, die in beiden Sprachen gleich bleiben (Auswahlwerte eines Generators).
TEMPLATE_VALUE_EXCEPTIONS = {"Kaltgeräte", "haengt", "steht_ab"}


def test_alle_mitgelieferten_vorlagen_englisch():
    with i18n.use_language("en"):
        templates = builtin_templates()
    assert len(templates) >= 30
    leaks = []
    for t in templates:
        assert t.localized, f"{t.name}: kein englischer Übersetzungsblock"
        texts = _template_texts(t)
        for field in texts["fields"]:
            if field["default_text"] in TEMPLATE_VALUE_EXCEPTIONS:
                del field["default_text"]
        leaks += [f"{t.name} {leak}" for leak in german_leaks(texts)]
    assert leaks == []


def test_vorlagen_ids_und_deutsch_unveraendert():
    with i18n.use_language("de"):
        de = {t.name: t for t in builtin_templates()}
    with i18n.use_language("en"):
        en = {t.name: t for t in builtin_templates()}
    assert set(de) == set(en)
    assert de["gefriergut"].description.startswith("Gefriergut mit Haltbarkeit")
    assert de["gefriergut"].title == "" and de["gefriergut"].display_title == "gefriergut"
    assert en["gefriergut"].display_title == "freezer"


def test_englische_vorlage_rendert_englischen_text(tmp_path):
    from tapesmith.templates.fill import CounterStore, build_document, resolve_values

    with i18n.use_language("en"):
        t = {t.name: t for t in builtin_templates()}["gefriergut"]
        values = {"inhalt": "Goulash", "kategorie": "Fish"}
        resolved = resolve_values(t, values, datetime(2026, 1, 1), CounterStore(tmp_path / "c.json"))
        doc = build_document(t, resolved.values)
    assert resolved.values["tage"] == "120"
    text = doc.objects[1].text
    assert text.startswith("Goulash\nFrozen 01.01.2026") and "until" in text


def test_lookup_findet_werte_der_anderen_sprache(tmp_path):
    from tapesmith.templates.fill import CounterStore, resolve_values

    with i18n.use_language("de"):
        t = {t.name: t for t in builtin_templates()}["gefriergut"]
    resolved = resolve_values(t, {"inhalt": "x", "kategorie": "Fish"}, datetime(2026, 1, 1),
                              CounterStore(tmp_path / "c.json"))
    assert resolved.values["tage"] == "120"


# ---------- CLI ----------

def _all_parsers(parser: argparse.ArgumentParser):
    yield parser
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for sub in action.choices.values():
                yield from _all_parsers(sub)


def test_cli_hilfe_vollstaendig_englisch(monkeypatch):
    monkeypatch.setenv("TAPESMITH_LANG", "en")
    parser = cli._parser(discover_commands())
    leaks = []
    count = 0
    for p in _all_parsers(parser):
        count += 1
        leaks += [f"{p.prog}: {line}" for line in text_leaks(p.format_help())]
    assert count > 100
    assert leaks == []


def test_cli_hilfe_deutsch_unveraendert(monkeypatch):
    monkeypatch.delenv("TAPESMITH_LANG", raising=False)
    help_text = cli._parser(discover_commands()).format_help()
    assert "Textlabel mit Auto-Fit drucken" in help_text


def _run(argv: list[str]) -> tuple[int, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            code = cli.main(argv)
        except SystemExit as exc:
            code = int(exc.code or 0)
    return code, out.getvalue() + err.getvalue()


@pytest.mark.parametrize("argv", [
    ["template", "list"], ["template", "show", "gefriergut"], ["template", "lint", "gefriergut"],
    ["template", "show", "does-not-exist"], ["text", "Hallo", "--preview", "{tmp}/p.png"],
    ["doctor", "--no-connect"], ["queue", "list"], ["history", "list"], ["module", "list"],
    ["status"], ["update", "status"], ["tape", "list"], ["config", "show"],
    ["does-not-exist"],
])
def test_cli_ausgaben_englisch(argv, monkeypatch, tmp_path):
    monkeypatch.setenv("TAPESMITH_LANG", "en")
    argv = [a.replace("{tmp}", str(tmp_path)) for a in argv]
    _code, output = _run(["--transport", f"file:{tmp_path / 'out.bin'}", *argv])
    output = output.replace("Hallo", "")
    assert text_leaks(output) == [], output


# ---------- Selbsttest und Support-Bericht ----------

def test_selbsttest_ausgabe_englisch(app_home, monkeypatch):
    from tapesmith import selftest

    monkeypatch.setenv("TAPESMITH_LANG", "en")
    out = io.StringIO()
    assert selftest.run_selftest(out) is True, out.getvalue()
    lines = out.getvalue().rstrip().splitlines()
    # letzte Zeile bleibt die feste Kennung, auf die Update und Build prüfen
    assert lines[-1] == selftest.OK_LINE
    leaks = text_leaks("\n".join(lines[:-1]))
    assert leaks == []
    assert any(line.startswith("OK Translations:") for line in lines)


def test_support_bericht_englisch(app_home, monkeypatch):
    import zipfile

    from tapesmith import support

    monkeypatch.setenv("TAPESMITH_LANG", "en")
    raw = support.build_report({"transport": "auto"}, status=None, now=datetime(2026, 9, 1, 12, 0))
    report = zipfile.ZipFile(io.BytesIO(raw)).read("bericht.txt").decode("utf-8")
    assert report.startswith("Tapesmith: problem report")
    assert text_leaks(report) == []


def test_alle_vorlagen_rendern_mit_englischen_meldungen(api):
    client, _ = api
    names = [t["name"] for t in client.get("/api/v1/templates", headers=EN).json()["templates"]]
    leaks = []
    for name in names:
        body = client.post("/api/v1/labels/render", json={"source": {"kind": "template", "template": name}},
                           headers=EN).json()
        body.pop("preview", None) if isinstance(body.get("preview"), str) else None
        leaks += [f"{name} {leak}" for leak in german_leaks(body)]
    assert leaks == []
