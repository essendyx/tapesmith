import dataclasses

import pytest

from tapesmith.device.profile import load_profile
from tapesmith.document.generators.raster import NO_FIELDS, NOT_CALIBRATED, PARAMS, generate, parse_assignment
from tapesmith.document.generators.raster_export import export_assignment
from tapesmith.document.render import render_document
from tapesmith.render.compose import mm_to_rows

PROFILE = load_profile()


def _belegung(n, prefix="P"):
    return "\n".join(f"{prefix}{i}" for i in range(1, n + 1))


def test_24_ports_keine_rundungsdrift():
    values = {"belegung": _belegung(24)}
    out = generate(PARAMS, values, PROFILE)
    fields = out.extra["fields"]
    assert len(fields) == 24
    for i, f in enumerate(fields, start=1):
        assert f["end_row"] == mm_to_rows(i * 15.875, PROFILE)
    assert mm_to_rows(out.document.length_mm, PROFILE) == mm_to_rows(24 * 15.875, PROFILE)


def test_24_ports_mit_kalibriertem_laengenfaktor():
    profile = dataclasses.replace(PROFILE, length_factor=1.0152, verified=PROFILE.verified + ("length",))
    values = {"belegung": _belegung(24)}
    out = generate(PARAMS, values, profile)
    fields = out.extra["fields"]
    for i, f in enumerate(fields, start=1):
        assert f["end_row"] == mm_to_rows(i * 15.875, profile)
    assert mm_to_rows(out.document.length_mm, profile) == mm_to_rows(24 * 15.875, profile)


def test_te_feldbreiten_und_bereichspruefung():
    params = PARAMS | {"einheit": "te", "te_mm": 17.5}
    out = generate(params, {"belegung": "FI|2\nKüche|1"}, PROFILE)
    fields = out.extra["fields"]
    assert fields[0]["width_mm"] == pytest.approx(35.0)
    assert fields[1]["width_mm"] == pytest.approx(17.5)

    with pytest.raises(ValueError, match="TE-Breite"):
        generate(params, {"belegung": "Zu breit|5"}, PROFILE)


def test_parse_assignment_gemischte_trenner():
    result = parse_assignment("a;b|2;;c")
    assert result == [("a", None), ("b", 2.0), ("", None), ("c", None)]


def test_frei_ohne_breite_nutzt_raster_mm_explizite_breite_bleibt_exakt():
    params = PARAMS | {"einheit": "frei", "raster_mm": 40}
    out = generate(params, {"belegung": "Schrauben|1\nDuebel"}, PROFILE)
    fields = out.extra["fields"]
    assert fields[0]["width_mm"] == pytest.approx(1.0)
    assert fields[1]["width_mm"] == pytest.approx(40.0)


def test_leere_felder_kein_textobjekt_und_keine_leer_warnung():
    values = {"belegung": "pmx10\npmx20\nNAS\n\nAP-OG"}
    out = generate(PARAMS, values, PROFILE)
    fields = out.extra["fields"]
    assert len(fields) == 5
    assert fields[3]["name"] == ""

    texts = [o for o in out.document.objects if o.kind == "text"]
    assert len(texts) == 4
    assert all(t.text for t in texts)

    dr = render_document(out.document, PROFILE)
    assert dr.ok
    assert not any("Text ist leer" in w.message for w in dr.warnings)

    assert mm_to_rows(out.document.length_mm, PROFILE) == mm_to_rows(5 * 15.875, PROFILE)


def test_nur_leerzeilen_ist_fehler():
    with pytest.raises(ValueError, match=NO_FIELDS):
        generate(PARAMS, {"belegung": "\n\n"}, PROFILE)


def test_kalibrierungshinweis():
    out = generate(PARAMS, {"belegung": "a\nb"}, PROFILE)
    assert NOT_CALIBRATED in out.notes

    calibrated = dataclasses.replace(PROFILE, length_factor=1.0152)
    out2 = generate(PARAMS, {"belegung": "a\nb"}, calibrated)
    assert NOT_CALIBRATED not in out2.notes


def test_export_assignment_csv_png_pdf_und_unbekanntes_format(tmp_path):
    out = generate(PARAMS, {"belegung": "a\nb|2"}, PROFILE)

    csv_path = export_assignment(out, tmp_path / "belegung.csv")
    data = csv_path.read_bytes()
    assert data.startswith(b"\xef\xbb\xbf")
    text = data.decode("utf-8-sig")
    assert text.splitlines()[0] == "Nr;Bezeichnung;Start (mm);Breite (mm)"
    assert "a" in text and "b" in text

    png_path = export_assignment(out, tmp_path / "belegung.png")
    from PIL import Image
    with Image.open(png_path) as img:
        assert img.width > 0

    pdf_path = export_assignment(out, tmp_path / "belegung.pdf")
    assert pdf_path.read_bytes().startswith(b"%PDF")

    with pytest.raises(ValueError, match="Exportformat"):
        export_assignment(out, tmp_path / "belegung.txt")


def test_snapshot_patchpanel(snapshot):
    values = {"belegung": "pmx10\npmx20\nNAS\n\nAP-OG"}
    out = generate(PARAMS, values, PROFILE)
    dr = render_document(out.document, PROFILE)
    assert dr.ok
    snapshot("gen-raster-patchpanel", dr.landscape)


def test_snapshot_sicherungskasten(snapshot):
    params = PARAMS | {"einheit": "te", "te_mm": 17.5}
    out = generate(params, {"belegung": "FI|2\nKüche|1\nBad|1\nHerd|3"}, PROFILE)
    dr = render_document(out.document, PROFILE)
    assert dr.ok
    snapshot("gen-raster-sicherungskasten", dr.landscape)
