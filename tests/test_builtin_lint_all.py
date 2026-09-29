"""Alle mitgelieferten Vorlagen: Lint ohne Fehler, Beispielwerte rendern ohne Ausnahme."""

from datetime import datetime

import pytest

from tapesmith.device.profile import load_profile
from tapesmith.templates.fill import CounterStore, resolve_values
from tapesmith.templates.lint import lint_templates, lint_values
from tapesmith.templates.render import render_template
from tapesmith.templates.store import builtin_templates

NOW = datetime(2026, 9, 27, 10, 0, 0)
BUILTIN = builtin_templates()


def test_lint_aller_vorlagen_ohne_fehler():
    errors = [i for i in lint_templates(BUILTIN, load_profile(), now=NOW) if i.level == "error"]
    assert errors == []


def test_mindestens_die_homelab_und_haushalts_vorlagen_dabei():
    names = {t.name for t in BUILTIN}
    assert {"datentraeger", "datentraeger-qr", "kabelfahne", "gefriergut", "asn"} <= names


@pytest.mark.parametrize("template", BUILTIN, ids=lambda t: t.name)
def test_vorlage_rendert_mit_beispiel(template, tmp_path):
    profile = load_profile()
    resolved = resolve_values(template, lint_values(template, "sample"), NOW,
                              CounterStore(tmp_path / "counters.json"))
    tr = render_template(template, resolved.values, profile)
    assert tr is not None
