"""Qt-freies `tapesmith.i18n` mit JSON-Katalogen unter `tapesmith/locales`."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from tapesmith import i18n, paths

REPO_ROOT = Path(__file__).resolve().parent.parent
LOCALES = REPO_ROOT / "src" / "tapesmith" / "locales"
DASHES = ("\u2013", "\u2014")
PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


@pytest.fixture(autouse=True)
def _frische_kataloge():
    i18n.reload_catalogs()
    yield
    i18n.reload_catalogs()


def test_uebersetzung_de_en():
    assert i18n.tr("errors.printer.busy.title", "de") == "Drucker belegt"
    assert i18n.tr("errors.printer.busy.title", "en") == "Printer busy"
    assert i18n.tr("common.app.name", "en") == "Tapesmith"
    assert i18n.tr("common.language.de", "de") == "Deutsch"


def test_rueckfall_auf_deutsch_und_schluessel(monkeypatch):
    real = i18n.catalog

    def fake(lang):
        data = real(lang)
        if lang == "en":
            data = {k: v for k, v in data.items() if k != "common"}
        return data

    monkeypatch.setattr(i18n, "catalog", fake)
    assert i18n.tr("common.theme.hell", "en") == "Hell"
    assert i18n.tr("gibt.es.nicht", "en") == "gibt.es.nicht"
    assert i18n.tr("common.gibtesnicht", "de") == "common.gibtesnicht"
    assert i18n.tr("common", "de") == "common"   # Knoten statt Text: Schlüssel zurück


def test_unbekannte_sprache_ist_deutsch():
    assert i18n.tr("errors.printer.busy.title", "fr") == "Drucker belegt"


def test_platzhalter():
    assert i18n.tr("common.units.mm", "de", value="38") == "38 mm"
    assert i18n.tr("common.units.mm", "en", value="38.5") == "38.5 mm"
    assert i18n.tr("common.units.mm", "de") == "{value} mm"   # fehlender Wert bleibt stehen


def test_tr_ohne_sprache_nutzt_die_einstellung(app_home):
    paths.config_path().write_text('{"app": {"language": "en"}}', encoding="utf-8")
    assert i18n.tr("errors.printer.busy.title") == "Printer busy"


def test_resolve_language():
    assert i18n.resolve_language("auto", system=lambda: "en") == "en"
    assert i18n.resolve_language("auto", system=lambda: "de") == "de"
    # Unbekannte Systemsprache: Englisch (die App wird international veröffentlicht)
    assert i18n.resolve_language("auto", system=lambda: None) == "en"
    assert i18n.resolve_language("auto", system=lambda: "fr") == "en"
    assert i18n.resolve_language(None, system=lambda: "en") == "en"
    assert i18n.resolve_language("en", system=lambda: "de") == "en"
    assert i18n.resolve_language("de", system=lambda: "en") == "de"
    # Unbekannte Einstellung wie "auto"
    assert i18n.resolve_language("xx", system=lambda: "de") == "de"

    def boom():
        raise OSError("kaputt")

    assert i18n.resolve_language("auto", system=boom) == "en"


def test_current_language(app_home):
    assert i18n.current_language({"app": {"language": "en"}}) == "en"
    # kaputte oder unbekannte Einstellung: Systemsprache (in Tests Deutsch)
    paths.config_path().write_text("{kaputt", encoding="utf-8")
    assert i18n.current_language() == "de"
    paths.config_path().write_text('{"app": {"language": "fr"}}', encoding="utf-8")
    assert i18n.current_language() == "de"


def test_current_language_folgt_der_systemsprache(app_home, monkeypatch):
    monkeypatch.setenv("TAPESMITH_SYSTEM_LANG", "en")
    assert i18n.current_language({"app": {"language": "auto"}}) == "en"
    assert i18n.current_language({"app": {"language": "de"}}) == "de"


def test_tapesmith_lang_erzwingt(app_home, monkeypatch):
    monkeypatch.setenv("TAPESMITH_LANG", "en-US")
    assert i18n.current_language({"app": {"language": "de"}}) == "en"
    assert i18n.default_language() == "en"
    monkeypatch.setenv("TAPESMITH_LANG", "fr")   # ungültig: ohne Wirkung
    assert i18n.current_language({"app": {"language": "de"}}) == "de"


@pytest.mark.parametrize("langid, expected", [(0x0407, "de"), (0x0C07, "de"), (0x0409, "en"),
                                              (0x0809, "en"), (0x040C, "en"), (0x0411, "en")])
def test_system_language_windows(langid, expected):
    assert i18n.system_language(reader=lambda: langid) == expected


def test_system_language_fehler_ist_englisch():
    def boom():
        raise OSError("kein kernel32")

    assert i18n.system_language(reader=boom) == "en"


def test_system_language_ersatz_fuer_tests(monkeypatch):
    monkeypatch.setenv("TAPESMITH_SYSTEM_LANG", "en")
    assert i18n.system_language() == "en"
    monkeypatch.setenv("TAPESMITH_SYSTEM_LANG", "de-AT")
    assert i18n.system_language() == "de"


def test_default_language_folgt_config(app_home):
    assert i18n.default_language() == "de"
    paths.config_path().write_text('{"app": {"language": "en"}}', encoding="utf-8")
    assert i18n.default_language() == "en"


@pytest.mark.parametrize("header, expected", [
    (None, None), ("", None), ("de-DE,de;q=0.9,en;q=0.8", "de"), ("en-US,en;q=0.9", "en"),
    ("fr-FR,fr;q=0.9", "en"), ("fr-FR,de;q=0.5", "de"), ("de;q=0.2,en;q=0.8", "en"), ("*", None),
    ("en;q=0,de", "de"),
])
def test_parse_accept_language(header, expected):
    assert i18n.parse_accept_language(header) == expected


def test_normalize():
    assert i18n.normalize("EN-gb") == "en"
    assert i18n.normalize("de_DE") == "de"
    assert i18n.normalize("fr") is None
    assert i18n.normalize(None) is None


def test_meldungen_mit_deutschem_text_als_kennung(app_home):
    msgid = "Vorlage '{name_or_path}' nicht gefunden (vorhanden: {names})"
    assert i18n.translate(msgid, "de", name_or_path="x", names="a") == "Vorlage 'x' nicht gefunden (vorhanden: a)"
    assert i18n.translate(msgid, "en", name_or_path="x", names="a") == "Template 'x' not found (available: a)"
    assert i18n.translate("gibt es nicht im Katalog", "en") == "gibt es nicht im Katalog"
    # ohne Parameter keine Formatierung (geschweifte Klammern bleiben)
    assert i18n.translate("{x}", "en") == "{x}"
    assert i18n.N_("egal") == "egal"


def test_use_language_setzt_die_sprache_der_anfrage(app_home):
    msgid = "Nicht gefunden"
    assert i18n._t(msgid) == "Nicht gefunden"
    with i18n.use_language("en") as lang:
        assert lang == "en"
        assert i18n.language() == "en"
        assert i18n._t(msgid) == "Not found"
        assert i18n.tr("errors.printer.busy.title") == "Printer busy"
        with i18n.use_language(None):
            assert i18n.language() == "de"
    assert i18n.request_language() is None
    assert i18n._t(msgid) == "Nicht gefunden"


def test_languages():
    assert i18n.LANGUAGES == ("de", "en")


# ---------- Katalog-Parität (alle vorhandenen Namespaces, auch spätere) ----------

def _flatten(node, prefix=""):
    out = {}
    for key, value in node.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            out.update(_flatten(value, path))
        else:
            out[path] = value
    return out


def _namespaces() -> list[str]:
    names = set()
    for lang in i18n.LANGUAGES:
        names |= {p.stem for p in (LOCALES / lang).glob("*.json")}
    return sorted(names)


def test_es_gibt_die_grund_namespaces():
    assert {"common", "errors"} <= set(_namespaces())


@pytest.mark.parametrize("namespace", _namespaces())
def test_katalog_paritaet(namespace):
    de = i18n.catalog("de").get(namespace)
    en = i18n.catalog("en").get(namespace)
    assert de is not None, f"de/{namespace}.json fehlt"
    assert en is not None, f"en/{namespace}.json fehlt"
    flat_de, flat_en = _flatten(de), _flatten(en)
    assert set(flat_de) == set(flat_en)
    for key in flat_de:
        for lang, value in (("de", flat_de[key]), ("en", flat_en[key])):
            assert isinstance(value, str) and value.strip(), f"{lang}/{namespace}:{key} leer"
            assert not any(d in value for d in DASHES), f"{lang}/{namespace}:{key} hat Gedankenstrich"
            assert " - " not in value, f"{lang}/{namespace}:{key} hat ' - '"
        assert set(PLACEHOLDER.findall(flat_de[key])) == set(PLACEHOLDER.findall(flat_en[key])), key


def test_i18n_ist_qt_frei():
    code = ("import tapesmith.i18n, tapesmith.support, tapesmith.webapi.drafts\n"
            "import sys\nprint('PySide6' in sys.modules, 'tapesmith.gui' in sys.modules)\n")
    env = dict(os.environ)
    src_path = str(REPO_ROOT / "src")
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = src_path if not existing else os.pathsep.join([src_path, existing])
    result = subprocess.run([sys.executable, "-c", code], env=env, cwd=str(REPO_ROOT), capture_output=True,
                            text=True, check=True)
    assert result.stdout.strip() == "False False", result.stdout + result.stderr
