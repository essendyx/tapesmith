"""Kern-API `reprint`: `load_entry`, `prepare_reprint`, `ReprintJob`, `MissingSecrets`."""

import json

import pytest
from PIL import Image

from tapesmith import paths
from tapesmith.device.profile import load_profile
from tapesmith.history import HistoryStore
from tapesmith.jobs import JobMeta
from tapesmith.reprint import MissingSecrets, load_entry, missing_secret_fields, prepare_reprint
from tapesmith.templates.fill import CounterStore


@pytest.fixture
def store(tmp_path):
    with HistoryStore(tmp_path / "history.sqlite3") as s:
        yield s


@pytest.fixture
def profile():
    return load_profile()


def test_load_entry_last_on_empty_store(store):
    with pytest.raises(ValueError, match="Verlauf ist leer"):
        load_entry(store, "last")


def test_load_entry_unknown_id(store):
    with pytest.raises(ValueError) as exc_info:
        load_entry(store, 999)
    assert str(exc_info.value) == "Verlaufseintrag 999 gibt es nicht"
    with pytest.raises(ValueError) as exc_info2:
        load_entry(store, "999")
    assert str(exc_info2.value) == "Verlaufseintrag 999 gibt es nicht"


def test_load_entry_neither_last_nor_id(store):
    with pytest.raises(ValueError, match="weder 'last' noch"):
        load_entry(store, "abc")


def test_prepare_reprint_from_head(store, profile):
    head = Image.new("1", (96, 80), 1)
    meta = JobMeta(kind="text", title="Kopf", values={}, sensitive=False)
    entry_id = store.record(meta, landscape=None, head=head, length_mm=10.0, tape_mm=12.0,
                            copies=3, chained=True)
    entry = load_entry(store, "last")
    assert entry.id == entry_id

    job = prepare_reprint(store, entry, profile, source="gui")
    assert job.from_image is True
    assert job.copies == 3
    assert job.chain is True
    assert job.labels[0].head.tobytes() == store.head_image(entry_id).tobytes()
    assert job.meta.kind == "reprint"
    assert job.meta.title.startswith("Nachdruck #")
    assert job.meta.source == "gui"

    overridden = prepare_reprint(store, entry, profile, copies=1, chain=False, source="gui")
    assert overridden.copies == 1
    assert overridden.chain is False


def _write_template(data: dict) -> None:
    tpl_dir = paths.app_dir() / "templates"
    tpl_dir.mkdir(exist_ok=True)
    (tpl_dir / f"{data['name']}.tapesmith.json").write_text(json.dumps(data), encoding="utf-8")


def test_prepare_reprint_sensitive_template(store, profile):
    _write_template({
        "schema_version": 1, "name": "wlan-test", "description": "",
        "fields": [
            {"id": "ssid", "label": "SSID", "type": "input"},
            {"id": "pw", "label": "Passwort", "type": "input", "secret": True},
        ],
        "layout": {"lines": ["{ssid}"], "qr": "WIFI:S:{ssid};P:{pw};;"},
    })
    meta = JobMeta(kind="template", template="wlan-test", values={"ssid": "Gast", "pw": "•••"},
                   sensitive=True)
    entry_id = store.record(meta, landscape=None, head=None, length_mm=5.0, tape_mm=6.0)
    entry = load_entry(store, entry_id)

    assert missing_secret_fields(store, entry) == ("pw",)

    with pytest.raises(MissingSecrets) as exc_info:
        prepare_reprint(store, entry, profile)
    assert exc_info.value.fields == ("pw",)

    job = prepare_reprint(store, entry, profile, sets={"pw": "geheim"})
    assert job.from_image is False
    assert job.result is not None
    assert "geheim" not in json.dumps(job.meta.to_dict())


def test_prepare_reprint_does_not_commit_counter_until_asked(store, profile, tmp_path):
    _write_template({
        "schema_version": 1, "name": "counter-test", "description": "",
        "fields": [{"id": "n", "label": "Nr", "type": "counter", "format": "{:03d}"}],
        "layout": {"lines": ["{n}"]},
    })
    meta = JobMeta(kind="template", template="counter-test", values={"n": "001"}, sensitive=False)
    entry_id = store.record(meta, landscape=None, head=None, length_mm=1.0, tape_mm=2.0)
    entry = load_entry(store, entry_id)

    counters = CounterStore(tmp_path / "counters.json")
    assert counters.peek("counter-test.n") == 1

    job = prepare_reprint(store, entry, profile, counters=counters)
    assert counters.peek("counter-test.n") == 1  # unverändert; nur "committen" erhöht den Zähler

    job.commit_counters()
    assert counters.peek("counter-test.n") == 2


# ---------- WLAN-QR ohne Vorlage (Integration QR-Seite/Verlauf) ----------

def _record_wifi(store, profile, *, lines=("Gast-WLAN",), error="l", max_mm=None):
    from tapesmith.labelmeta import qr_meta
    from tapesmith.render.compose import render_label
    from tapesmith.render.qrcontent import build_qr_spec, wifi_content

    content = wifi_content("Gast", "geheim123", security="WPA", hidden=True)
    spec = build_qr_spec(content, lines, error, max_mm)
    result = render_label(spec, profile)
    meta = qr_meta(content, lines, source="gui", spec=spec)
    entry_id = store.record(meta, landscape=result.landscape, head=result.head,
                            length_mm=result.length_mm, tape_mm=result.tape_mm, status="ok")
    return entry_id, content


def test_wifi_qr_eintrag_ohne_klartext(store, profile):
    entry_id, _content = _record_wifi(store, profile)
    entry = store.get(entry_id)
    assert entry.sensitive and not entry.has_head and entry.template is None
    assert "geheim123" not in json.dumps(entry.to_dict(), ensure_ascii=False)
    assert missing_secret_fields(store, entry) == ("password",)


def test_wifi_qr_nachdruck_braucht_passwort(store, profile):
    entry_id, _content = _record_wifi(store, profile)
    with pytest.raises(MissingSecrets) as exc_info:
        prepare_reprint(store, store.get(entry_id), profile)
    assert exc_info.value.fields == ("password",)


def test_wifi_qr_nachdruck_baut_gleiches_label(store, profile):
    import zxingcpp

    entry_id, content = _record_wifi(store, profile, max_mm=40.0)
    original = store.get(entry_id)
    job = prepare_reprint(store, original, profile, sets={"password": "geheim123"}, source="gui")
    assert job.from_image is False
    assert job.result.qr is not None and job.result.qr.error.upper() == "L"
    decoded = zxingcpp.read_barcodes(job.result.landscape.convert("L"))
    assert [d.text for d in decoded] == [content.data]
    assert job.meta.sensitive is True
    assert job.meta.kind == "reprint"
    assert job.meta.title.startswith(f"Nachdruck #{entry_id}: ")
    assert "geheim123" not in json.dumps(job.meta.to_dict(), ensure_ascii=False)

    # Der Nachdruck ist selbst wieder nachdruckbar.
    again_id = store.record(job.meta, landscape=job.result.landscape, head=job.result.head,
                            length_mm=job.result.length_mm, tape_mm=job.result.tape_mm, status="ok")
    assert missing_secret_fields(store, store.get(again_id)) == ("password",)


def test_sensibler_eintrag_ohne_vorlage_und_ohne_qr_daten(store, profile):
    from tapesmith.history import is_reprintable

    entry_id = store.record(JobMeta(kind="qr", title="WLAN alt", values={"qr": "WLAN alt (Passwort •••)"},
                                    sensitive=True),
                            landscape=None, head=None, length_mm=10, tape_mm=12, status="ok")
    entry = store.get(entry_id)
    assert is_reprintable(entry) is False
    with pytest.raises(ValueError, match="kann nicht nachgedruckt werden"):
        missing_secret_fields(store, entry)
