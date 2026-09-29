"""Plausibilität der Metadaten aller mitgelieferten Vorlagen: Beschreibung, Kategorie, Stichworte,
Feldbezeichnungen, Standardwerte, Pflichtfelder und Beispielwerte."""

import re

import pytest

from tapesmith.templates.fill import input_fields
from tapesmith.templates.store import builtin_templates

BUILTIN = builtin_templates()
DASH = re.compile("[\u2013\u2014]|\\s-\\s")


@pytest.mark.parametrize("template", BUILTIN, ids=lambda t: t.name)
def test_metadaten(template):
    problems = []
    t = template
    if len(t.description) < 20 or not t.description.rstrip().endswith((".", ")")):
        problems.append(f"Beschreibung zu knapp oder ohne Satzende: {t.description!r}")
    if not t.category:
        problems.append("Kategorie fehlt")
    if not t.tags:
        problems.append("Stichworte fehlen")
    if not t.sample:
        problems.append("Beispielwerte fehlen")
    if not 1 <= t.default_copies <= 10:
        problems.append("default_copies außerhalb 1..10")
    labels = [f.label for f in t.fields]
    if len(set(labels)) != len(labels):
        problems.append(f"Feldbezeichnungen doppelt: {labels}")
    for f in t.fields:
        if not f.label.strip() or f.label == f.id:
            problems.append(f"Feld {f.id}: Bezeichnung fehlt (nur ID)")
        if f.label != f.label.strip() or f.label.endswith((":", "*")):
            problems.append(f"Feld {f.id}: Bezeichnung mit Rand/Doppelpunkt/Stern {f.label!r}")
        if f.choices and f.default and f.default not in f.choices:
            problems.append(f"Feld {f.id}: Standard {f.default!r} nicht unter den Auswahlwerten")
    for f in input_fields(t):
        if f.required and not t.sample.get(f.id, "").strip():
            problems.append(f"Pflichtfeld {f.id} ohne Beispielwert")
        value = t.sample.get(f.id, "")
        if f.max_len and len(value) > f.max_len:
            problems.append(f"Beispiel {f.id} länger als max_len {f.max_len}")
        if f.choices and value and value not in f.choices:
            problems.append(f"Beispiel {f.id} nicht unter den Auswahlwerten")
    for f in t.fields:
        if f.id in t.description and "_" in f.id:
            problems.append(f"Beschreibung nennt die technische Feld-ID {f.id} statt der Bezeichnung")
    for text in [t.description, *labels]:
        if DASH.search(text):
            problems.append(f"Gedankenstrich in {text!r}")
    assert problems == []
