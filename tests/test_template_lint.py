"""Vorlagen-Lint: `lint_values`, `lint_template`, `lint_templates`."""

import json

from tapesmith import paths
from tapesmith.device.profile import load_profile
from tapesmith.templates.lint import lint_template, lint_templates, lint_values
from tapesmith.templates.model import template_from_dict
from tapesmith.templates.store import builtin_templates

PROFILE = load_profile()


def test_builtin_templates_have_no_errors():
    for issue in lint_templates(builtin_templates(), PROFILE):
        assert issue.level != "error", issue


def test_overflow_in_max_dataset_only():
    template = template_from_dict({
        "schema_version": 2, "name": "t-overflow", "description": "",
        "fields": [{"id": "host", "label": "Host", "type": "input", "max_len": 60,
                    "default": "pmx10"}],
        "layout": {"lines": ["{host}"], "fixed_length_mm": 20},
        "sample": {"host": "pmx10"},
    })
    issues = lint_template(template, PROFILE)
    by_data = {}
    for issue in issues:
        by_data.setdefault(issue.data, []).append(issue)
    assert not any(i.level == "error" for i in by_data.get("Beispiel", []))
    assert any(i.level == "error" for i in by_data.get("Maximal", []))


def test_small_fixed_font_and_narrow_code128_and_thin_line():
    template = template_from_dict({
        "schema_version": 2, "name": "t-doc-issues", "description": "",
        "fields": [{"id": "host", "label": "Host", "type": "input", "default": "pmx10"}],
        "document": {
            "objects": [
                {"kind": "text", "id": "t1", "x": 0, "y": 0, "w": 200, "h": 40,
                 "text": "{host}", "size": 8},
                {"kind": "code128", "id": "c1", "x": 0, "y": 45, "w": 10, "h": 30,
                 "data": "{host}"},
                {"kind": "line", "id": "l1", "x": 0, "y": 80, "w": 100, "h": 4, "thickness": 1},
            ],
        },
        "sample": {"host": "pmx10"},
    })
    issues = lint_template(template, PROFILE)
    messages = [(i.level, i.message) for i in issues]
    assert any(level == "error" and "Schrift zu klein" in msg for level, msg in messages)
    assert any(level == "error" and "c1" in msg for level, msg in messages)
    assert any(level == "warning" and "l1" in msg for level, msg in messages)


def test_template_without_sample_warns():
    template = template_from_dict({
        "schema_version": 2, "name": "t-nosample", "description": "",
        "fields": [{"id": "host", "label": "Host", "type": "input", "default": "pmx10"}],
        "layout": {"lines": ["{host}"]},
    })
    issues = lint_template(template, PROFILE)
    assert any("Keine Beispieldaten" in i.message for i in issues)


def test_lint_does_not_advance_real_counter(tmp_path):
    template = template_from_dict({
        "schema_version": 2, "name": "zaehler-lint", "description": "",
        "fields": [{"id": "n", "label": "Nr", "type": "counter", "format": "{:03d}"}],
        "layout": {"lines": ["{n}"]},
        "sample": {},
    })
    counters_path = paths.app_dir() / "counters.json"
    lint_template(template, PROFILE)
    lint_template(template, PROFILE)
    assert not counters_path.exists()


def test_lint_values_max_mode_widens_choices_and_max_len_but_keeps_serial():
    template = template_from_dict({
        "schema_version": 2, "name": "t-values", "description": "",
        "fields": [
            {"id": "slot", "label": "Slot", "type": "input", "choices": ["a", "bb", "ccc"]},
            {"id": "note", "label": "Note", "type": "input", "max_len": 5},
            {"id": "sn", "label": "SN", "type": "input", "clean": "serial"},
        ],
        "layout": {"lines": ["{slot}"]},
        "sample": {"sn": "112233274913"},
    })
    values = lint_values(template, "max")
    assert values["slot"] == "ccc"
    assert values["note"] == "W" * 5
    assert values["sn"] == "112233274913"
