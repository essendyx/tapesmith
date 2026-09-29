"""`clipboard.py`: Zwischenablage-Erkennung und Rendern des Druckvorschlags. Kein Qt,
keine echte Zwischenablage."""

import json
from datetime import datetime

import pytest
from PIL import Image

from tapesmith.clipboard import (
    LONG_URL,
    MAX_PER_LINE_LABELS,
    TWO_LINE_SIZE,
    ClipKind,
    ClipSuggestion,
    classify_clipboard,
    normalize_text,
    render_suggestion,
)
from tapesmith.device.profile import load_profile
from tapesmith.tape.profiles import find_tape
from tapesmith.templates.fill import CounterStore
from tapesmith.templates.model import template_from_dict
from tapesmith.templates.store import SUFFIX, user_dir

PROFILE = load_profile()


# 1. classify_clipboard: Tabelle -------------------------------------------------------------

def test_serial_erkannt():
    s = classify_clipboard("S4EWNX0R123456")
    assert s.kind is ClipKind.SERIAL
    assert s.action == "template"
    assert s.template == "datentraeger"
    assert s.values == {"sn": "S4EWNX0R123456"}


def test_serial_mit_praefix_wird_bereinigt():
    s = classify_clipboard("SN: S4EWNX0R123456")
    assert s.kind is ClipKind.SERIAL
    assert s.values == {"sn": "S4EWNX0R123456"}


def test_byid_erkannt():
    s = classify_clipboard("ata-Samsung_SSD_870_EVO_1TB_S5Y1NX0R123456")
    assert s.kind is ClipKind.BYID
    assert s.action == "template"
    assert s.template == "datentraeger"
    assert s.values == {"sn": "ata-Samsung_SSD_870_EVO_1TB_S5Y1NX0R123456"}


def test_byid_ohne_seriennummer_ableitbar_wird_text_mit_hinweis():
    s = classify_clipboard("wwn-0x5002538e")
    assert s.action == "text"
    assert s.lines == ("wwn-0x5002538e",)
    assert s.note


def test_url_https():
    s = classify_clipboard("https://paperless.lan/documents/12/")
    assert s.kind is ClipKind.URL
    assert s.action == "qr"
    assert s.lines == ("paperless.lan",)
    assert s.qr == "https://paperless.lan/documents/12/"


def test_url_www():
    s = classify_clipboard("www.example.com")
    assert s.kind is ClipKind.URL
    assert s.qr == "https://www.example.com"
    assert s.lines == ("example.com",)


def test_ipv4():
    s = classify_clipboard("192.0.2.60")
    assert s.kind is ClipKind.IPV4
    assert s.action == "template"
    assert s.template == "ip-label"
    assert s.values == {"ip": "192.0.2.60"}


def test_ipv4_ungueltiges_octett_ist_text():
    s = classify_clipboard("192.0.2.600")
    assert s.kind is ClipKind.TEXT


def test_mac_mit_trennern():
    s = classify_clipboard("00:11:22:33:44:55")
    assert s.kind is ClipKind.MAC
    assert s.action == "text"
    assert s.lines == ("00:11:22:33:44:55",)
    assert s.font == "mono"


def test_mac_ohne_trenner():
    s = classify_clipboard("001122334455")
    assert s.kind is ClipKind.MAC
    assert s.lines == ("00:11:22:33:44:55",)


def test_freitext_mit_leerzeichen():
    s = classify_clipboard("pmx10 SSD-1")
    assert s.kind is ClipKind.TEXT
    assert s.lines == ("pmx10 SSD-1",)


def test_zwei_zeilen():
    s = classify_clipboard("Zeile 1\r\nZeile 2")
    assert s.kind is ClipKind.TWO_LINES
    assert s.lines == ("Zeile 1", "Zeile 2")
    assert s.font_size == TWO_LINE_SIZE == 44


def test_fuenf_zeilen_mehrzeilig():
    s = classify_clipboard("a\nb\nc\nd\ne")
    assert s.kind is ClipKind.MULTILINE
    assert s.action == "lines"
    assert s.lines == ("a", "b", "c", "d", "e")
    assert "5 Zeilen" in s.title
    assert s.note == ""


def test_sechzig_zeilen_wird_auf_50_gekuerzt():
    text = "\n".join(f"z{i}" for i in range(60))
    s = classify_clipboard(text)
    assert s.kind is ClipKind.MULTILINE
    assert len(s.lines) == MAX_PER_LINE_LABELS == 50
    assert "50" in s.note


def test_leer():
    assert classify_clipboard("").kind is ClipKind.EMPTY
    assert classify_clipboard(None).kind is ClipKind.EMPTY
    assert classify_clipboard("").action == "none"


def test_bild():
    img = Image.new("1", (10, 10), 255)
    s = classify_clipboard(None, image=img)
    assert s.kind is ClipKind.IMAGE
    assert s.action == "image"
    assert s.image is img


def test_kurzer_text_ist_nicht_seriennummer():
    assert classify_clipboard("hallo").kind is ClipKind.TEXT


def test_text_ohne_ziffer_ist_nicht_seriennummer():
    assert classify_clipboard("ABCDEFGH").kind is ClipKind.TEXT


# 2. Lange URL -> Hinweis --------------------------------------------------------------------

def test_lange_url_bekommt_kurzlink_hinweis():
    url = "https://beispiel.lan/" + "x" * 60
    assert len(url) > LONG_URL
    s = classify_clipboard(url)
    assert s.kind is ClipKind.URL
    assert "Kurz-Link" in s.note


# 3a. Zähler: render_suggestion zählt nie selbst (nur peek) ----------------------------------

ZAEHLER_TEMPLATE = {
    "schema_version": 2, "name": "clip-zaehler-test", "description": "",
    "fields": [{"id": "nr", "label": "Nummer", "type": "counter", "format": "{:03d}"}],
    "layout": {"lines": ["Nr {nr}"]},
}


def test_zaehler_wird_nur_gepeekt_zentraler_zaehler_bleibt_unberuehrt(tmp_path):
    template_path = user_dir() / f"clip-zaehler-test{SUFFIX}"
    template_path.write_text(json.dumps(ZAEHLER_TEMPLATE), encoding="utf-8")

    zentral = tmp_path / "zentral" / "counters.json"
    s = ClipSuggestion(ClipKind.SERIAL, "t", "template", template="clip-zaehler-test", values={})
    render = render_suggestion(s, PROFILE, counters=CounterStore(zentral))

    assert render.meta.values["nr"] == "001"
    assert render.counter_keys
    assert not zentral.exists()

    from tapesmith import paths
    assert not (paths.app_dir() / "counters.json").exists()


# 3. render_suggestion für die einzelnen Aktionen ---------------------------------------------

def test_render_text_suggestion():
    s = classify_clipboard("Hallo Welt")
    render = render_suggestion(s, PROFILE)
    assert len(render.labels) == 1
    assert render.labels[0].head.width == PROFILE.head_dots
    assert render.meta.source == "hotkey"
    assert render.meta.kind == "text"


def test_render_two_lines_suggestion():
    s = classify_clipboard("Zeile 1\nZeile 2")
    render = render_suggestion(s, PROFILE)
    assert len(render.labels) == 1
    assert render.meta.kind == "text"


def test_render_qr_suggestion():
    s = classify_clipboard("https://paperless.lan/documents/12/")
    render = render_suggestion(s, PROFILE)
    assert len(render.labels) == 1
    assert render.meta.kind == "qr"
    assert render.meta.values["url"] == s.qr


def test_render_template_ip_suggestion():
    s = classify_clipboard("192.0.2.60")
    render = render_suggestion(s, PROFILE)
    assert len(render.labels) == 1
    assert render.meta.kind == "template"


def test_render_template_datentraeger_suggestion():
    s = classify_clipboard("S4EWNX0R123456")
    render = render_suggestion(s, PROFILE)
    assert len(render.labels) == 1
    assert render.meta.kind == "template"
    assert render.tape_reason is None or isinstance(render.tape_reason, str)


def test_render_image_suggestion():
    img = Image.new("1", (200, 40), 255)
    s = classify_clipboard(None, image=img)
    render = render_suggestion(s, PROFILE)
    assert len(render.labels) == 1
    assert render.meta.kind == "image"


def test_render_lines_per_label_drei_zeilen():
    s = classify_clipboard("a\nb\nc")
    render = render_suggestion(s, PROFILE)
    assert len(render.labels) == 3
    assert "Kette" in render.balance_text


def test_render_lines_per_line_false_bei_fuenf_zeilen_wirft():
    s = classify_clipboard("a\nb\nc\nd\ne")
    with pytest.raises(ValueError):
        render_suggestion(s, PROFILE, per_line=False)


def test_render_lines_per_line_false_bei_drei_zeilen_ein_label():
    s = classify_clipboard("a\nb\nc")
    render = render_suggestion(s, PROFILE, per_line=False)
    assert len(render.labels) == 1


# 4. Band weiss-schwarz + URL: Kopfbild unterscheidet sich vom hellen Band --------------------

def test_dunkles_band_veraendert_kopfbild_bei_qr():
    s = classify_clipboard("https://paperless.lan/documents/12/")
    hell = render_suggestion(s, PROFILE, tape=find_tape("schwarz-weiss"))
    dunkel = render_suggestion(s, PROFILE, tape=find_tape("weiss-schwarz"))
    assert hell.labels[0].head.tobytes() != dunkel.labels[0].head.tobytes()


# 5. EMPTY -> render_suggestion wirft ---------------------------------------------------------

def test_empty_render_wirft():
    s = classify_clipboard(None)
    with pytest.raises(ValueError):
        render_suggestion(s, PROFILE)


# normalize_text --------------------------------------------------------------------------

def test_normalize_text_strip_und_leere_randzeilen():
    assert normalize_text("\r\n  a  \r\nb\r\n\r\n") == ("a", "b")
    assert normalize_text("") == ()
