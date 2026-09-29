import pytest
import segno
from PIL import Image

from tapesmith.render.qr import render_qr, self_test


def test_short_uppercase_url_is_v1_with_4_dot_modules():
    r = render_qr("HTTP://L.LAN/D7", 88)
    assert (r.version, r.module_dots, r.error) == (1, 4, "M")
    assert r.image.mode == "1" and r.image.size == (84, 84)
    assert r.decodes is True
    assert r.warnings == ()


def test_serial_number_decodes():
    r = render_qr("S4EWNX0R123456", 88)
    assert r.decodes


def test_version_3_warns_about_quiet_zone():
    r = render_qr("A" * 60, 88)
    assert r.version == 3 and r.module_dots == 3
    assert any("Ruhezone" in w for w in r.warnings)


def test_small_module_warns():
    r = render_qr("A" * 60, 60)
    assert r.module_dots == 2
    assert any("Modul" in w for w in r.warnings)
    assert r.decodes is True


def test_too_long_raises():
    with pytest.raises(ValueError, match="passt nicht lesbar"):
        render_qr("x" * 1000, 88)


def test_module_1_is_rejected():
    data = "x" * 120
    n = segno.make_qr(data, error="m", boost_error=False).symbol_size(border=0)[0]
    assert 88 // n == 1
    with pytest.raises(ValueError, match="Modul 1 Punkte"):
        render_qr(data, 88)


def test_failed_self_test_is_rejected(monkeypatch):
    import tapesmith.render.qr as qr_mod

    monkeypatch.setattr(qr_mod, "self_test", lambda *a: False)
    with pytest.raises(ValueError, match="passt nicht lesbar"):
        render_qr("ABC", 88)


def test_self_test_rejects_blank():
    assert self_test(Image.new("1", (42, 42), 255), "x", 2) is False
