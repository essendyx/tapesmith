from datetime import datetime

import pytest

from tapesmith.device.profile import load_profile
from tapesmith.document.generators import run_generator
from tapesmith.document.render import render_document
from tapesmith.templates.fill import CounterStore, resolve_values
from tapesmith.templates.store import find_template

PROFILE = load_profile()
NOW = datetime(2026, 9, 27)

TEMPLATE_NAMES = (
    "kabelfahne", "kabelwickel",
    "raster-patchpanel", "raster-switch", "raster-sicherungskasten", "raster-sortiment",
)


def _max_data_inputs(template):
    inputs = {}
    for f in template.fields:
        if f.type != "input":
            continue
        if f.max_len:
            inputs[f.id] = "W" * f.max_len
        elif f.choices:
            inputs[f.id] = max(f.choices, key=len)
        else:
            inputs[f.id] = template.sample.get(f.id, f.default)
    return inputs


@pytest.mark.parametrize("name", TEMPLATE_NAMES)
def test_alle_vorlagen_laden_und_sind_generator_vorlagen(name):
    template = find_template(name)
    assert template.kind == "generator"


@pytest.mark.parametrize("name", TEMPLATE_NAMES)
def test_beispieldaten_rendern_ohne_fehler(name, tmp_path):
    template = find_template(name)
    resolved = resolve_values(template, template.sample, NOW, CounterStore(tmp_path / "counters.json"))
    output = run_generator(template.generator, resolved.values, PROFILE)
    dr = render_document(output.document, PROFILE)
    assert dr.ok, [i.message for i in dr.errors]
    assert not any("Text ist leer" in w.message for w in dr.warnings)


@pytest.mark.parametrize("name", TEMPLATE_NAMES)
def test_maximaldaten_rendern_ohne_fehler_und_lesbare_schrift(name, tmp_path):
    template = find_template(name)
    inputs = _max_data_inputs(template)
    resolved = resolve_values(template, inputs, NOW, CounterStore(tmp_path / "counters.json"))
    output = run_generator(template.generator, resolved.values, PROFILE)
    dr = render_document(output.document, PROFILE)
    assert dr.ok, [i.message for i in dr.errors]
    assert all(size >= 16 for size in dr.font_sizes.values())
