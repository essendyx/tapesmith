import pytest
import zxingcpp

from tapesmith.device.profile import load_profile
from tapesmith.render.qr import render_qr
from tapesmith.render.qrcontent import (
    best_error_level,
    build_qr_spec,
    capacity_report,
    escape_wifi,
    text_content,
    url_content,
    vcard_content,
    wifi_content,
)

P = load_profile()


# 1. url_content --------------------------------------------------------

def test_url_content_adds_https_scheme_by_default():
    assert url_content("l.lan/d7").data == "https://l.lan/d7"


def test_url_content_uppercase_uses_upper_link():
    assert url_content("l.lan/d7", uppercase=True).data == "HTTPS://L.LAN/D7"


def test_url_content_rejects_non_http_scheme():
    with pytest.raises(ValueError):
        url_content("ftp://x")
    with pytest.raises(ValueError):
        url_content("FTP://X")


def test_url_content_rejects_spaces():
    with pytest.raises(ValueError):
        url_content("https://a b")


def test_url_content_keeps_existing_scheme_case_and_no_double_scheme():
    assert url_content("HTTP://L.LAN/D7").data == "HTTP://L.LAN/D7"
    assert url_content("Https://l.lan/x").data == "Https://l.lan/x"


def test_url_content_display_and_secret():
    c = url_content("l.lan/d7")
    assert c.display == c.data
    assert c.secret is False


# 2. escape_wifi ----------------------------------------------------------

def test_escape_wifi_masks_special_chars_backslash_first():
    assert escape_wifi('a;b,c:d"e\\f') == 'a\\;b\\,c\\:d\\"e\\\\f'


# 3+4. wifi_content ---------------------------------------------------------

def test_wifi_content_wpa_masks_ssid_and_password_and_hides_secret():
    c = wifi_content("Heim;Netz", "pw:1")
    assert c.data == "WIFI:T:WPA;S:Heim\\;Netz;P:pw\\:1;;"
    assert c.secret is True
    assert "pw:1" not in c.display
    assert "•••" in c.display


def test_wifi_content_nopass():
    c = wifi_content("Gast", security="nopass")
    assert c.data == "WIFI:T:nopass;S:Gast;;"
    assert c.secret is False


def test_wifi_content_hidden_adds_h_true():
    c = wifi_content("Gast", security="nopass", hidden=True)
    assert "H:true;" in c.data


def test_wifi_content_security_aliases_and_case():
    assert wifi_content("Gast", "geheim12", security="WPA2").data.startswith("WIFI:T:WPA;")
    assert wifi_content("Gast", "geheim12", security="wpa").data.startswith("WIFI:T:WPA;")


def test_wifi_content_wpa_without_password_raises():
    with pytest.raises(ValueError):
        wifi_content("Gast", security="WPA")


def test_wifi_content_nopass_with_password_raises():
    with pytest.raises(ValueError):
        wifi_content("Gast", "geheim12", security="nopass")


def test_wifi_content_unknown_security_raises():
    with pytest.raises(ValueError):
        wifi_content("Gast", security="XYZ")


# 5. vcard_content ----------------------------------------------------------

def test_vcard_content_builds_expected_lines():
    c = vcard_content("Max", phone="+49 123", email="a@b.de")
    assert c.data.startswith("BEGIN:VCARD\nVERSION:3.0\n")
    assert c.data.endswith("END:VCARD")
    assert "TEL:+49 123" in c.data
    assert "EMAIL:a@b.de" in c.data


def test_vcard_content_requires_name():
    with pytest.raises(ValueError):
        vcard_content("")


def test_vcard_content_rejects_newline_in_name():
    with pytest.raises(ValueError):
        vcard_content("Max\nMustermann")


# 6. capacity_report --------------------------------------------------------

def test_capacity_report_short_url_is_version_1_and_decodes():
    cap = capacity_report(url_content("HTTP://L.LAN/D7", uppercase=False), P)
    assert cap.version == 1
    assert cap.decodes is True
    assert "Selbsttest ok" in cap.text()


# 7. Selbsttest-Rücklesen ----------------------------------------------------

def test_wifi_qr_round_trips_exactly_through_zxing():
    wifi = wifi_content("Heimnetz", "abcdefgh12345678")
    level = best_error_level(wifi, P)
    result = render_qr(wifi.data, P.content_dots, level)
    texts = [r.text for r in zxingcpp.read_barcodes(result.image)]
    assert wifi.data in texts


# 8. Unlesbar -----------------------------------------------------------

def test_capacity_report_raises_for_very_long_text():
    c = text_content("x" * 300)
    with pytest.raises(ValueError, match="passt nicht lesbar.*Kurz-Link"):
        capacity_report(c, P, "m")


def test_capacity_report_warns_for_module_2():
    cap = capacity_report(text_content("x" * 60), P, "m")
    assert cap.module_dots == 2
    assert any("QR-Modul nur 2 Punkte" in w for w in cap.warnings)


def test_capacity_report_raises_for_module_1():
    with pytest.raises(ValueError, match="passt nicht lesbar"):
        capacity_report(text_content("x" * 120), P, "m")


def test_best_error_level_raises_same_message_when_unreadable():
    c = text_content("x" * 300)
    with pytest.raises(ValueError, match="passt nicht lesbar"):
        best_error_level(c, P)


def test_capacity_report_wraps_render_qr_value_error(monkeypatch):
    from tapesmith.render import qrcontent

    def fake(*args, **kwargs):
        raise ValueError("zu lang")

    monkeypatch.setattr(qrcontent, "render_qr", fake)
    with pytest.raises(ValueError, match="passt nicht lesbar"):
        capacity_report(text_content("x" * 10), P, "m")


def test_capacity_report_positive_case_with_quiet_zone_warning():
    cap = capacity_report(text_content("x" * 30), P, "m")
    assert cap.version == 3
    assert cap.module_dots == 3
    assert any("Ruhezone" in w for w in cap.warnings)


# 9. best_error_level --------------------------------------------------------

def test_best_error_level_short_text_is_m():
    assert best_error_level(text_content("x" * 14), P) == "m"


def test_best_error_level_prefers_l_when_it_reaches_version_2():
    assert best_error_level(text_content("x" * 30), P) == "l"


def test_best_error_level_wifi_stays_m():
    wifi = wifi_content("Heimnetz", "abcdefgh12345678")
    assert best_error_level(wifi, P) == "m"


# 10. build_qr_spec -----------------------------------------------------

def test_build_qr_spec_sets_qr_and_lines():
    content = wifi_content("Gast", security="nopass")
    spec = build_qr_spec(content, ["Gast-WLAN"])
    assert spec.qr == content.data
    assert spec.lines == ("Gast-WLAN",)


# 11. best_error_level zieht Kandidaten ohne Modulwarnung vor (Regression) ---------

@pytest.mark.parametrize("n", [45, 50])
def test_best_error_level_prefers_l_without_module_warning(n):
    content = text_content("x" * n)
    level = best_error_level(content, P)
    assert level == "l"
    cap = capacity_report(content, P, level)
    assert cap.module_dots == 3
    assert not any("Modul" in w for w in cap.warnings)


def test_best_error_level_falls_back_to_warning_candidate():
    # Nur noch mit 2-Punkt-Modul darstellbar: Level wird trotzdem gewählt (mit Warnung).
    for n in range(50, 200, 5):
        content = text_content("x" * n)
        caps = {}
        for lv in ("m", "l"):
            try:
                caps[lv] = capacity_report(content, P, lv)
            except ValueError:
                pass
        if caps and all(c.module_dots < 3 for c in caps.values()):
            level = best_error_level(content, P)
            assert level in caps
            assert level == ("m" if "m" in caps else "l")
            return
    pytest.skip("kein reiner Warnungsfall gefunden")
