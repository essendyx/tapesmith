"""Homelab- und Haushalts-/Büro-Vorlagen inkl. ASN (Code128), mit Snapshots."""

from datetime import datetime

import pytest
import zxingcpp

from tapesmith.device.profile import load_profile
from tapesmith.document.model import bbox, find_object
from tapesmith.render.icons import render_icon
from tapesmith.tape.profiles import find_tape
from tapesmith.templates.fill import CounterStore, resolve_values
from tapesmith.templates.lint import lint_template
from tapesmith.templates.render import render_template
from tapesmith.templates.store import find_template

NOW = datetime(2026, 9, 27, 12, 0)
PROFILE = load_profile()

HOMELAB = ("host-ip", "vm-lxc", "passthrough", "netzteil", "netzteil-warnung",
           "psu-paar", "asset-tag", "ip-label")
HAUSHALT = ("gefriergut", "geoeffnet-am", "vorratsdose", "aufbewahrungsbox", "preis",
            "reserviert", "schule", "eigentum")
BUERO = ("netzteil-zuordnung", "ordnerruecken-schmal", "ordnerruecken-breit", "absender",
         "asn", "garantie")
ALL_NAMES = HOMELAB + HAUSHALT + BUERO
CATEGORY = {name: "Homelab" for name in HOMELAB}
CATEGORY.update({name: "Haushalt" for name in HAUSHALT})
CATEGORY.update({name: "Büro" for name in BUERO})


def _resolved(name, tmp_path, inputs=None):
    t = find_template(name)
    values = inputs if inputs is not None else t.sample
    return t, resolve_values(t, values, NOW, CounterStore(tmp_path / "c.json")).values


@pytest.mark.parametrize("name", ALL_NAMES)
def test_vorlage_laedt_mit_schema_v2_und_metadaten(name):
    t = find_template(name)
    assert t.schema_version == 2
    assert t.category == CATEGORY[name]
    assert len(t.tags) >= 2
    input_ids = {f.id for f in t.fields if f.type == "input"}
    required_ids = {f.id for f in t.fields if f.type == "input" and f.required}
    assert required_ids <= set(t.sample) | {i for i in required_ids if t.field(i).default}


@pytest.mark.parametrize("name", ALL_NAMES)
def test_vorlage_rendert_beispieldaten_ohne_fehler_und_snapshot(name, tmp_path, snapshot):
    t, values = _resolved(name, tmp_path)
    tr = render_template(t, values, PROFILE)
    snapshot(f"tpl-{name}", tr.result.landscape)


@pytest.mark.parametrize("name", ALL_NAMES)
def test_vorlage_lint_ohne_fehler(name):
    issues = lint_template(find_template(name), PROFILE, now=NOW)
    errors = [i for i in issues if i.level == "error"]
    assert errors == [], errors


def test_gefriergut_gemuese_datum(tmp_path):
    t, values = _resolved("gefriergut", tmp_path, {"inhalt": "Erbsen", "kategorie": "Gemüse"})
    assert values["bis"] == "27.09.2027"


def test_garantie_datum(tmp_path):
    t, values = _resolved("garantie", tmp_path,
                          {"geraet": "Kaffeemaschine", "kaufdatum": "31.01.2026", "dauer": "24"})
    assert values["ende"] == "31.01.2028"


def test_geoeffnet_am_laenge_25mm(tmp_path):
    t, values = _resolved("geoeffnet-am", tmp_path)
    tr = render_template(t, values, PROFILE)
    assert abs(tr.result.length_mm - 25) < 0.2


def test_ordnerruecken_laengen(tmp_path):
    for name, mm in (("ordnerruecken-schmal", 190), ("ordnerruecken-breit", 280)):
        t, values = _resolved(name, tmp_path)
        tr = render_template(t, values, PROFILE)
        assert abs(tr.result.length_mm - mm) < 0.2


def test_host_ip_kurzer_host_wird_nicht_gekuerzt(tmp_path):
    t, values = _resolved("host-ip", tmp_path, {"host": "pmx10", "ip": "192.0.2.60", "rolle": "Hauptserver"})
    tr = render_template(t, values, PROFILE)
    assert tr.shortened == ()
    assert tr.values["host"] == "pmx10"


def test_host_ip_langer_host_wird_ohne_domain_gekuerzt(tmp_path):
    t, values = _resolved("host-ip", tmp_path, {
        "host": "sehr-langer-hostname.example.internal", "ip": "192.0.2.60", "rolle": "Hauptserver"})
    tr = render_template(t, values, PROFILE)
    assert any("ohne Domain" in s for s in tr.shortened)
    assert tr.values["host"] == "sehr-langer-hostname"


def test_asset_tag_qr_dekodiert(tmp_path):
    t, values = _resolved("asset-tag", tmp_path)
    tr = render_template(t, values, PROFILE)
    box = bbox(find_object(t.document, "qr1"))
    crop = tr.result.landscape.crop(box).convert("L")
    results = zxingcpp.read_barcodes(crop, formats=zxingcpp.BarcodeFormat.QRCode)
    assert any(r.text == "HTTP://L.LAN/HL-0042" for r in results)


def test_vorratsdose_alle_symbole_haben_ein_icon(tmp_path):
    t = find_template("vorratsdose")
    symbol_field = t.field("symbol")
    icon_field = t.field("icon")
    icon_map = icon_field.map_dict()
    for choice in symbol_field.choices:
        ref = icon_map[choice]
        render_icon(ref, 32)


def test_netzteil_warnung_schraffur_anteil(tmp_path, pixel_counts):
    t, values = _resolved("netzteil-warnung", tmp_path)
    tr = render_template(t, values, PROFILE)
    box = bbox(find_object(t.document, "rect1"))
    crop = tr.result.landscape.crop(box)
    counts = pixel_counts(crop)
    black = counts.get(0, 0)
    total = crop.width * crop.height
    ratio = black / total
    assert 0.35 <= ratio <= 0.65, ratio


def test_gefriergut_papierband_ausloest_rueckfrage(tmp_path):
    t, values = _resolved("gefriergut", tmp_path)
    tape = find_tape("schwarz-weiss-papier")
    tr = render_template(t, values, PROFILE, tape=tape)
    assert tr.tape_reason is not None


def test_asn_rueckgelesen_beispiel_und_maximaldaten(tmp_path, pixel_counts):
    t = find_template("asn")

    def check(asn_value):
        values = resolve_values(t, {"asn": asn_value}, NOW, CounterStore(tmp_path / "c.json")).values
        tr = render_template(t, values, PROFILE)
        assert abs(tr.result.length_mm - 64) < 0.2
        assert not tr.issues or all(i.level != "error" for i in tr.issues)
        results = zxingcpp.read_barcodes(tr.result.landscape.convert("L"),
                                         formats=zxingcpp.BarcodeFormat.Code128)
        assert any(r.text == asn_value for r in results)
        # unterste Zeilen enthalten Tinte (Klartext), aber nicht die volle Balkenbreite
        bottom = tr.result.landscape.crop((0, tr.result.landscape.height - 10,
                                           tr.result.landscape.width, tr.result.landscape.height))
        counts = pixel_counts(bottom)
        assert counts.get(0, 0) > 0
        assert counts.get(0, 0) < bottom.width * bottom.height

    check("ASN01234")
    check("W" * 10)

    issues_max = lint_template(t, PROFILE, now=NOW)
    assert [i for i in issues_max if i.level == "error"] == []
