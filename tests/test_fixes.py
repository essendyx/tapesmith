import time
from dataclasses import replace

from tapesmith.device.profile import load_profile
from tapesmith.render.compose import LabelSpec
from tapesmith.render.fixes import ELLIPSIS, apply_fix, diagnose, suggest_fixes

P = load_profile()


def test_unproblematisch_hat_keine_vorschlaege():
    spec = LabelSpec(lines=("SSD-1",))
    assert diagnose(spec, P).ok
    assert suggest_fixes(spec, P) == []


def test_feste_schrift_zu_gross_verkleinern_und_laenger():
    spec = LabelSpec(lines=("pmx10 SSD-1 SN 274913",), font_size=60, max_length_mm=30)
    diag = diagnose(spec, P)
    assert diag.error is not None

    fixes = suggest_fixes(spec, P)
    by_id = {f.id: f for f in fixes}
    assert "verkleinern" in by_id
    assert "laenger" in by_id
    for fix in fixes:
        assert fix.result is not None
    assert by_id["verkleinern"].spec.font_size is None


def test_ueberlaenge_laenger_erhoeht_bis_es_passt():
    spec = LabelSpec(lines=("Sehr langer Kabelname 123456",), max_length_mm=15)
    diag = diagnose(spec, P)
    assert diag.error is not None or any("Schrift sehr klein" in w for w in diag.warnings)

    fixes = suggest_fixes(spec, P)
    by_id = {f.id: f for f in fixes}
    assert "laenger" in by_id
    laenger = by_id["laenger"]
    assert isinstance(laenger.spec.max_length_mm, int)
    assert laenger.spec.max_length_mm > 15
    result_diag = diagnose(laenger.spec, P)
    assert result_diag.error is None
    assert not any("Schrift sehr klein" in w for w in result_diag.warnings)

    kleiner = diagnose(replace(spec, max_length_mm=laenger.spec.max_length_mm - 1), P)
    assert kleiner.error is not None or any("Schrift sehr klein" in w for w in kleiner.warnings)


def test_kuerzen_fuer_ueberlaenge():
    spec = LabelSpec(lines=("Sehr langer Kabelname 123456",), max_length_mm=15)
    fixes = suggest_fixes(spec, P)
    by_id = {f.id: f for f in fixes}
    assert "kuerzen" in by_id
    kuerzen = by_id["kuerzen"]
    neue_zeile = kuerzen.spec.lines[0]
    assert neue_zeile.endswith(ELLIPSIS)
    assert len(neue_zeile) < len(spec.lines[0])
    result_diag = diagnose(kuerzen.spec, P)
    assert result_diag.error is None
    assert not any("Schrift sehr klein" in w for w in result_diag.warnings)


def test_kuerzen_kuerzt_nur_die_laengste_zeile():
    spec = LabelSpec(
        lines=("Sehr langer Kabelname 123456", "kurz"),
        max_length_mm=15,
    )
    fixes = suggest_fixes(spec, P)
    by_id = {f.id: f for f in fixes}
    assert "kuerzen" in by_id
    kuerzen = by_id["kuerzen"]
    assert kuerzen.spec.lines[1] == "kurz"
    assert kuerzen.spec.lines[0] != spec.lines[0]
    assert kuerzen.spec.lines[0].endswith(ELLIPSIS)


def test_qr_ecc_l_reduziert_version_und_warnungen():
    spec = LabelSpec(qr="abcdefghij" * 3)
    diag = diagnose(spec, P)
    assert diag.result is not None
    assert diag.result.qr.version == 3
    assert any("Version 3" in w for w in diag.warnings)

    fixes = suggest_fixes(spec, P)
    by_id = {f.id: f for f in fixes}
    assert "qr_ecc_l" in by_id
    qr_fix = by_id["qr_ecc_l"]
    assert qr_fix.spec.qr_error == "l"
    assert len(qr_fix.result.warnings) < len(diag.warnings)


def test_qr_ecc_l_nicht_angeboten_wenn_schon_l():
    spec = LabelSpec(qr="abcdefghij" * 3, qr_error="l")
    fixes = suggest_fixes(spec, P)
    assert "qr_ecc_l" not in {f.id for f in fixes}


def test_zentrieren_unabhaengig_von_warnungen():
    spec = LabelSpec(lines=("A",), fixed_length_mm=40)
    assert diagnose(spec, P).ok
    fixes = suggest_fixes(spec, P)
    assert [f.id for f in fixes] == ["zentrieren"]
    assert fixes[0].spec.align == "center"

    zentriert = replace(spec, align="center")
    assert suggest_fixes(zentriert, P) == []


def test_apply_fix_verhalten():
    spec = LabelSpec(lines=("Sehr langer Kabelname 123456",), max_length_mm=15)
    fixes = suggest_fixes(spec, P)
    by_id = {f.id: f for f in fixes}

    applied = apply_fix(spec, P, "laenger")
    assert applied == by_id["laenger"]

    try:
        apply_fix(spec, P, "gibtsnicht")
        assert False, "sollte ValueError werfen"
    except ValueError as exc:
        assert "Unbekannte Korrektur" in str(exc)

    unproblematisch = LabelSpec(lines=("SSD-1",))
    try:
        apply_fix(unproblematisch, P, "kuerzen")
        assert False, "sollte ValueError werfen"
    except ValueError as exc:
        assert "passt hier nicht" in str(exc)


def test_suggest_fixes_ist_deterministisch():
    spec = LabelSpec(lines=("pmx10 SSD-1 SN 274913",), font_size=60, max_length_mm=30)
    a = suggest_fixes(spec, P)
    b = suggest_fixes(spec, P)
    assert [f.id for f in a] == [f.id for f in b]
    assert [f.spec for f in a] == [f.spec for f in b]


def test_laufzeit_laenger_und_kuerzen_unter_5s():
    spec = LabelSpec(lines=("Sehr langer Kabelname 123456",), max_length_mm=15)
    start = time.perf_counter()
    suggest_fixes(spec, P)
    elapsed = time.perf_counter() - start
    assert elapsed < 5.0
