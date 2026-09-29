"""Meldungs-Katalog (`tapesmith/locales/messages/<sprache>.json`): vollständig und paritätisch.

Jede Kennung im Quelltext (`_t("...")`, `N_("...")`, `translate("...")`, siehe `tapesmith.i18n`) hat
eine Übersetzung mit denselben Platzhaltern, der Katalog enthält nichts Verwaistes, keine leeren
Texte und keine Gedankenstriche. Pflege: `python tools/i18n_messages.py`.
"""

from __future__ import annotations

import re
import string
import sys
from pathlib import Path

import pytest

from tapesmith import i18n

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import i18n_messages  # noqa: E402

DASHES = (chr(0x2013), chr(0x2014))


def _fields(text: str) -> list[str]:
    out = []
    for _literal, name, spec, conv in string.Formatter().parse(text):
        if name is not None:
            out.append(f"{name}!{conv or ''}:{spec or ''}")
    return sorted(out)


@pytest.fixture(scope="module")
def msgids() -> dict[str, list[str]]:
    return i18n_messages.collect_msgids()


def test_es_gibt_kennungen(msgids):
    assert len(msgids) > 1000


def test_keine_fstrings_als_kennung():
    assert i18n_messages.fstring_calls() == []


def test_keine_leeren_kennungen(msgids):
    bad = [f"{where[0]}: {k!r}" for k, where in msgids.items() if len(k.strip()) < 2]
    assert bad == []


@pytest.mark.parametrize("lang", i18n_messages.LANGS)
def test_katalog_vollstaendig_und_ohne_verwaiste(lang, msgids):
    data = i18n_messages.load_catalog(lang)
    missing = sorted(set(msgids) - set(data))
    orphans = sorted(set(data) - set(msgids))
    assert missing == [], f"{len(missing)} fehlen in {lang}, z. B. {missing[:5]} ({msgids[missing[0]][0]})"
    assert orphans == [], f"{len(orphans)} verwaist in {lang}, z. B. {orphans[:5]}"


@pytest.mark.parametrize("lang", i18n_messages.LANGS)
def test_platzhalter_und_form(lang, msgids):
    data = i18n_messages.load_catalog(lang)
    problems = []
    for msgid, text in data.items():
        if not isinstance(text, str) or not text.strip():
            problems.append(f"leer: {msgid!r}")
            continue
        if _fields(msgid) != _fields(text):
            problems.append(f"Platzhalter: {msgid!r} -> {text!r}")
        if any(d in text for d in DASHES):
            problems.append(f"Gedankenstrich: {text!r}")
        if " - " in text and " - " not in msgid:
            problems.append(f"' - ': {text!r}")
        if re.search(r"[äöüÄÖÜß]", text) and not re.search(r"[äöüÄÖÜß]", msgid):
            problems.append(f"Umlaut: {text!r}")
    assert problems == []


def test_katalog_geladen_und_uebersetzt():
    i18n.reload_catalogs()
    assert i18n.translate("Drucker bereit", "en") == "Printer ready"
    assert i18n.translate("Drucker bereit", "de") == "Drucker bereit"
    assert i18n.messages("de") == {}
