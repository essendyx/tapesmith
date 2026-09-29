"""`reprint.prepare_reprint`: Band-Parameter beim Nachdruck."""

import json

import pytest

from tapesmith import paths
from tapesmith.device.profile import load_profile
from tapesmith.history import HistoryStore
from tapesmith.jobs import JobMeta
from tapesmith.reprint import load_entry, prepare_reprint
from tapesmith.tape.profiles import find_tape


@pytest.fixture
def store(tmp_path):
    with HistoryStore(tmp_path / "history.sqlite3") as s:
        yield s


@pytest.fixture
def profile():
    return load_profile()


def _write_template(data: dict) -> None:
    tpl_dir = paths.app_dir() / "templates"
    tpl_dir.mkdir(exist_ok=True)
    (tpl_dir / f"{data['name']}.tapesmith.json").write_text(json.dumps(data), encoding="utf-8")


# 23. Vorlagen-Nachdruck mit QR und sensiblem Feld -------------------------------------------

def _sensitive_qr_entry(store) -> int:
    _write_template({
        "schema_version": 1, "name": "wlan-tape-test", "description": "",
        "fields": [
            {"id": "ssid", "label": "SSID", "type": "input"},
            {"id": "pw", "label": "Passwort", "type": "input", "secret": True},
        ],
        "layout": {"lines": ["{ssid}"], "qr": "WIFI:S:{ssid};P:{pw};;"},
    })
    meta = JobMeta(kind="template", template="wlan-tape-test", values={"ssid": "Gast", "pw": "•••"},
                   sensitive=True)
    return store.record(meta, landscape=None, head=None, length_mm=5.0, tape_mm=6.0)


def test_prepare_reprint_with_explicit_dark_tape_differs_from_no_tape(store, profile):
    entry_id = _sensitive_qr_entry(store)
    entry = load_entry(store, entry_id)

    dark = prepare_reprint(store, entry, profile, sets={"pw": "geheim"},
                           tape=find_tape("weiss-schwarz"))
    light = prepare_reprint(store, entry, profile, sets={"pw": "geheim"}, tape=None)
    assert dark.result.head.tobytes() != light.result.head.tobytes()


def test_prepare_reprint_without_tape_argument_uses_config(store, profile):
    entry_id = _sensitive_qr_entry(store)
    entry = load_entry(store, entry_id)

    explicit_dark = prepare_reprint(store, entry, profile, sets={"pw": "geheim"},
                                    tape=find_tape("weiss-schwarz"))

    paths.config_path().write_text(json.dumps({"tape": {"current": "weiss-schwarz"}}), encoding="utf-8")
    from_config = prepare_reprint(store, entry, profile, sets={"pw": "geheim"})
    assert from_config.result.head.tobytes() == explicit_dark.result.head.tobytes()


def test_prepare_reprint_without_tape_config_matches_previous_behaviour(store, profile):
    entry_id = _sensitive_qr_entry(store)
    entry = load_entry(store, entry_id)

    no_config = prepare_reprint(store, entry, profile, sets={"pw": "geheim"})
    explicit_none = prepare_reprint(store, entry, profile, sets={"pw": "geheim"}, tape=None)
    assert no_config.result.head.tobytes() == explicit_none.result.head.tobytes()


# 24. WLAN-Nachdruck ohne Vorlage --------------------------------------------------------

def _record_wifi(store, profile):
    from tapesmith.labelmeta import qr_meta
    from tapesmith.render.compose import render_label
    from tapesmith.render.qrcontent import build_qr_spec, wifi_content

    content = wifi_content("Gast", "geheim123", security="WPA", hidden=True)
    spec = build_qr_spec(content, (), "l", None)
    result = render_label(spec, profile)
    meta = qr_meta(content, (), source="gui", spec=spec)
    return store.record(meta, landscape=result.landscape, head=result.head,
                        length_mm=result.length_mm, tape_mm=result.tape_mm, status="ok")


def test_wifi_reprint_with_dark_tape_inverts(store, profile):
    entry_id = _record_wifi(store, profile)
    entry = load_entry(store, entry_id)

    dark = prepare_reprint(store, entry, profile, sets={"password": "geheim123"},
                           tape=find_tape("weiss-schwarz"))
    light = prepare_reprint(store, entry, profile, sets={"password": "geheim123"}, tape=None)
    assert dark.result.head.tobytes() != light.result.head.tobytes()
