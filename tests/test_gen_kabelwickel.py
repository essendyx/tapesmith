import math

import pytest

from tapesmith.device.profile import load_profile
from tapesmith.document.generators.kabelwickel import PARAMS, TOO_FEW_REPEATS, TOO_THIN, generate
from tapesmith.document.render import render_document
from tapesmith.render.compose import mm_to_rows

PROFILE = load_profile()


def test_laenge_wiederholungen_und_wrap_rows():
    values = {"kabel_id": "K1", "kabeltyp": "Cat6"}
    out = generate(PARAMS, values, PROFILE)
    expected_length = mm_to_rows(2 * math.pi * 6.2, PROFILE)
    assert mm_to_rows(out.document.length_mm, PROFILE) == expected_length

    texts = [o for o in out.document.objects if o.kind == "text"]
    assert len(texts) == out.extra["repeats"] >= 2
    sizes = {t.size for t in texts}
    assert len(sizes) == 1
    assert all(t.text == "K1" for t in texts)

    assert out.extra["wrap_rows"] == mm_to_rows(math.pi * 6.2, PROFILE)
    assert out.extra["wrap_rows"] + out.extra["overlap_rows"] == expected_length

    dr = render_document(out.document, PROFILE)
    assert dr.ok


def test_lwl_beide_warnungen():
    out = generate(PARAMS, {"kabel_id": "K-017-lang", "kabeltyp": "LWL"}, PROFILE)
    assert TOO_THIN in out.warnings
    assert TOO_FEW_REPEATS in out.warnings


def test_lange_id_auf_duennem_kabel_nur_einmal():
    out = generate(PARAMS, {"kabel_id": "SEHR-LANGE-KABEL-ID-0001", "kabeltyp": "DAC"}, PROFILE)
    assert out.extra["repeats"] == 1
    assert TOO_FEW_REPEATS in out.warnings


def test_kabel_id_pflicht():
    with pytest.raises(ValueError, match="kabel_id"):
        generate(PARAMS, {"kabeltyp": "Cat6"}, PROFILE)


def test_snapshot(snapshot):
    out = generate(PARAMS, {"kabel_id": "K-017", "kabeltyp": "Cat6"}, PROFILE)
    dr = render_document(out.document, PROFILE)
    assert dr.ok
    snapshot("gen-kabelwickel", dr.landscape)
