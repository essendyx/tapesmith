from datetime import datetime

import pytest

from tapesmith.render.compose import LabelSpec
from tapesmith.templates.fill import REDACTED, CounterStore, build_spec, expand, redact, redact_text, resolve_values
from tapesmith.templates.model import TemplateError, template_from_dict

NOW = datetime(2026, 9, 27, 10, 30)

T = template_from_dict({
    "schema_version": 1, "name": "t", "description": "",
    "fields": [
        {"id": "host", "label": "Host", "type": "input", "default": "pmx10"},
        {"id": "sn", "label": "Seriennummer", "type": "input", "clean": "serial", "required": True},
        {"id": "datum", "label": "Datum", "type": "date", "format": "%d.%m.%Y", "offset_days": 90},
        {"id": "nr", "label": "Nr", "type": "counter", "format": "{:04d}"},
        {"id": "firma", "label": "Firma", "type": "fixed", "default": "DMS"},
        {"id": "pw", "label": "Passwort", "type": "input", "secret": True},
    ],
    "layout": {"lines": ["{host} · {sn|last:6}", "{nr} {datum}"], "qr": "{sn}", "font": "mono",
               "max_length_mm": 40},
})


@pytest.fixture
def counters(tmp_path):
    return CounterStore(tmp_path / "counters.json")


def test_resolve_all_types(counters):
    r = resolve_values(T, {"sn": "ata-SanDisk_SDSSDHP256G_112233274913", "pw": "geheim"}, NOW, counters)
    v = r.values
    assert v["host"] == "pmx10" and v["firma"] == "DMS"
    assert v["sn"] == "112233274913" and v["sn_model"] == "SanDisk SDSSDHP256G"
    assert v["datum"] == "26.12.2026"
    assert v["nr"] == "0001" and r.counter_keys == ("t.nr",)


def test_counter_only_advances_on_commit(counters):
    assert resolve_values(T, {"sn": "1"}, NOW, counters).values["nr"] == "0001"
    assert resolve_values(T, {"sn": "1"}, NOW, counters).values["nr"] == "0001"
    assert counters.commit("t.nr") == 1
    assert resolve_values(T, {"sn": "1"}, NOW, counters).values["nr"] == "0002"
    assert CounterStore(counters.path).peek("t.nr") == 2


def test_required_missing(counters):
    with pytest.raises(TemplateError, match="Seriennummer"):
        resolve_values(T, {"sn": "  "}, NOW, counters)


def test_unknown_input_rejected(counters):
    with pytest.raises(TemplateError, match="unbekannt"):
        resolve_values(T, {"sn": "1", "farbe": "rot"}, NOW, counters)


@pytest.mark.parametrize("field_id", ["firma", "datum", "nr"])
def test_set_on_non_input_field_rejected(counters, field_id):
    with pytest.raises(TemplateError, match="nicht eingebbar"):
        resolve_values(T, {"sn": "1", field_id: "x"}, NOW, counters)


def test_expand_filters():
    values = {"sn": "112233274913", "h": "pmx10"}
    assert expand("SN {sn|last:6}", values) == "SN 274913"
    assert expand("{sn|first:4}{h|upper}", values) == "1122PMX10"
    assert expand("{h|upper|lower}", values) == "pmx10"
    with pytest.raises(TemplateError, match="Filter"):
        expand("{h|rot}", values)
    with pytest.raises(TemplateError, match="unbekannt"):
        expand("{x}", values)


def test_build_spec(counters):
    values = resolve_values(T, {"sn": "112233274913"}, NOW, counters).values
    spec = build_spec(T, values)
    assert spec == LabelSpec(lines=("pmx10 · 274913", "0001 26.12.2026"), qr="112233274913", font="mono",
                             max_length_mm=40)


def test_redact(counters):
    values = resolve_values(T, {"sn": "1", "pw": "geheim"}, NOW, counters).values
    safe = redact(T, values)
    assert safe["pw"] == REDACTED and safe["sn"] == "1"
    assert values["pw"] == "geheim"


SECRET_SERIAL_TEMPLATE = template_from_dict({
    "schema_version": 1, "name": "sec", "description": "",
    "fields": [
        {"id": "sn", "label": "Seriennummer", "type": "input", "clean": "serial", "secret": True},
        {"id": "pw", "label": "Passwort", "type": "input", "secret": True},
    ],
    "layout": {"lines": ["{sn}"]},
})


def test_redact_masks_derived_model_field_of_secret_serial(counters):
    values = resolve_values(SECRET_SERIAL_TEMPLATE, {"sn": "ata-SanDisk_SDSSDHP256G_112233274913"}, NOW, counters).values
    safe = redact(SECRET_SERIAL_TEMPLATE, values)
    assert safe["sn"] == REDACTED
    assert safe["sn_model"] == REDACTED


def test_redact_text_masks_secret_values_longest_first():
    values = {"pw": "geheim123", "sn": "12", "sn_model": ""}
    text = redact_text("WLAN geheim123 / SN 12", SECRET_SERIAL_TEMPLATE, values)
    assert text == f"WLAN {REDACTED} / SN {REDACTED}"


def test_redact_text_ignores_empty_secret_values():
    values = {"pw": "", "sn": "", "sn_model": ""}
    text = redact_text("nichts Geheimes hier", SECRET_SERIAL_TEMPLATE, values)
    assert text == "nichts Geheimes hier"


def test_counter_commit_is_atomic_and_leaves_lock_file(tmp_path):
    store = CounterStore(tmp_path / "counters.json")
    store.commit("k")
    assert [p.name for p in tmp_path.iterdir()] == sorted(["counters.json", "counters.json.lock"])
