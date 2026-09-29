from datetime import datetime, timedelta

import pytest

from tapesmith.templates.fill import CounterStore, build_document, build_spec, resolve_values
from tapesmith.templates.model import TemplateError, template_from_dict

NOW = datetime(2026, 9, 27, 10, 30)


@pytest.fixture
def counters(tmp_path):
    return CounterStore(tmp_path / "counters.json")


LOOKUP_TEMPLATE = template_from_dict({
    "schema_version": 2, "name": "lookup-test", "description": "",
    "fields": [
        {"id": "kategorie", "label": "Kategorie", "type": "input", "choices": ["Fleisch", "Gemüse"],
         "default": "Fleisch"},
        {"id": "tage", "label": "Haltbar (Tage)", "type": "lookup", "source": "kategorie",
         "map": {"Fleisch": "180", "Gemüse": "365"}},
        {"id": "bis", "label": "Haltbar bis", "type": "date", "offset_field": "tage"},
    ],
    "layout": {"lines": ["{kategorie}", "{bis}"]},
})


def test_lookup_resolves_from_source_field(counters):
    r = resolve_values(LOOKUP_TEMPLATE, {"kategorie": "Gemüse"}, NOW, counters)
    assert r.values["tage"] == "365"


def test_date_offset_field_adds_days_from_lookup(counters):
    r = resolve_values(LOOKUP_TEMPLATE, {"kategorie": "Gemüse"}, NOW, counters)
    expected = (NOW + timedelta(days=365)).strftime("%d.%m.%Y")
    assert r.values["bis"] == expected


DATE_TEMPLATE = template_from_dict({
    "schema_version": 2, "name": "garantie", "description": "",
    "fields": [
        {"id": "kaufdatum", "label": "Kaufdatum", "type": "input", "default": "31.01.2026"},
        {"id": "monate", "label": "Monate", "type": "input", "default": "1"},
        {"id": "garantieende", "label": "Garantieende", "type": "date", "base_field": "kaufdatum",
         "offset_months_field": "monate"},
    ],
    "layout": {"lines": ["{kaufdatum}", "{garantieende}"]},
})


def test_base_field_and_offset_months_field_clamp_month_end(counters):
    r = resolve_values(DATE_TEMPLATE, {}, NOW, counters)
    assert r.values["garantieende"] == "28.02.2026"


def test_unreadable_base_date_raises_clear_error(counters):
    with pytest.raises(TemplateError, match=r"Kaufdatum.*nicht lesbar"):
        resolve_values(DATE_TEMPLATE, {"kaufdatum": "32.13.2026"}, NOW, counters)


def test_non_numeric_offset_field_raises_clear_error(counters):
    with pytest.raises(TemplateError, match=r"Monate.*keine ganze Zahl"):
        resolve_values(DATE_TEMPLATE, {"monate": "abc"}, NOW, counters)


COUNTER_TEMPLATE = template_from_dict({
    "schema_version": 2, "name": "zaehler", "description": "",
    "fields": [{"id": "nr", "label": "Nr", "type": "counter", "format": "{:04d}"}],
    "layout": {"lines": ["{nr}"]},
})


def test_counter_offset_shifts_the_peeked_value(counters):
    r = resolve_values(COUNTER_TEMPLATE, {}, NOW, counters, counter_offset=2)
    assert r.values["nr"] == "0003"
    assert r.counter_keys == ("zaehler.nr",)


DOCUMENT_TEMPLATE = template_from_dict({
    "schema_version": 2, "name": "doc-fill", "description": "",
    "fields": [
        {"id": "sn", "label": "SN", "type": "input"},
        {"id": "kategorie", "label": "Kategorie", "type": "input", "default": "Fleisch"},
        {"id": "symbol", "label": "Symbol", "type": "lookup", "source": "kategorie",
         "map": {"Fleisch": "tabler:snowflake", "Gemüse": "tabler:snowflake"}},
    ],
    "document": {
        "version": 1,
        "objects": [
            {"kind": "text", "id": "t1", "x": 0, "y": 0, "w": 200, "h": 40, "text": "SN {sn|last:6}"},
            {"kind": "qr", "id": "q1", "x": 0, "y": 45, "w": 60, "h": 60, "data": "{sn}"},
            {"kind": "icon", "id": "i1", "x": 65, "y": 45, "w": 40, "h": 40, "icon": "{symbol}"},
        ],
    },
})


def test_build_document_replaces_placeholders_with_filters_and_lookup(counters):
    values = resolve_values(DOCUMENT_TEMPLATE, {"sn": "112233274913"}, NOW, counters).values
    doc = build_document(DOCUMENT_TEMPLATE, values)
    by_id = {o.id: o for o in doc.objects}
    assert by_id["t1"].text == "SN 274913"
    assert by_id["q1"].data == "112233274913"
    assert by_id["i1"].icon == "tabler:snowflake"


def test_build_spec_on_document_template_raises(counters):
    values = resolve_values(DOCUMENT_TEMPLATE, {"sn": "1"}, NOW, counters).values
    with pytest.raises(TemplateError, match="kein layout"):
        build_spec(DOCUMENT_TEMPLATE, values)
