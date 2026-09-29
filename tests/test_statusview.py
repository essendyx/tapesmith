from datetime import datetime, timedelta

import pytest

from tapesmith.ipc.codec import StateInfo, StatusReport
from tapesmith.status import PrinterStatus, StatusValue
from tapesmith.statusview import age_text, status_view

NOW = datetime(2026, 9, 27, 12, 0, 0)
CONNECTED = StateInfo("verbunden", "COM4")


def value(kind, v, text="", verified=True):
    return StatusValue(kind=kind, value=v, text=text or f"{kind} {v}", verified=verified, raw=b"")


def report(*values, raw=b"\x1a\x04\x4b", checked=NOW - timedelta(minutes=3), state=CONNECTED):
    status = PrinterStatus(values={v.kind: v for v in values}, unknown=[], raw=raw)
    return StatusReport(state=state, status=status, checked_at=checked)


def full_report(**kw):
    return report(value("battery", 75), value("lid", "zu"), value("paper", "ok"),
                  value("firmware", "1.0.6"), value("serial", "P12ABC"), value("media", "Lücken"), **kw)


def lines(view):
    return view.detail.splitlines()


def test_connected_with_verified_battery():
    view = status_view(CONNECTED, full_report(), now=NOW)
    assert view.chip == "P12 · verbunden (COM4) · Akku 75 %"
    assert view.role == "success"
    assert view.title == "Tapesmith: verbunden (COM4) · Akku 75 %"
    assert "Akku: 75 %" in lines(view)
    assert "Deckel: zu" in lines(view)
    assert "Firmware: 1.0.6" in lines(view)
    assert "Seriennummer: P12ABC" in lines(view)
    assert "Medium: Lücken" in lines(view)
    assert "Transport: COM4" in lines(view)
    assert "Zuletzt abgefragt: vor 3 min" in lines(view)
    assert "MAC: nicht verfügbar" in lines(view)
    assert view.tooltip == "verbunden (COM4) · Akku 75 % · Status vor 3 min"


def test_mac_from_config_and_from_status():
    view = status_view(CONNECTED, full_report(), now=NOW, mac="00:11:22:33:44:55")
    assert "MAC: 00:11:22:33:44:55 (aus Konfiguration, unbestätigt)" in lines(view)
    compact = status_view(CONNECTED, full_report(), now=NOW, mac="001122334455")
    assert "MAC: 00:11:22:33:44:55 (aus Konfiguration, unbestätigt)" in lines(compact)
    mac_value = StatusValue(kind="mac", value="00:11:22:33:44:55", text="MAC 00:11:22:33:44:55",
                            verified=False, raw=b"")
    from_status = status_view(CONNECTED, report(value("battery", 75), mac_value), now=NOW, mac="00:11:22:33:44:55")
    assert "MAC: 00:11:22:33:44:55 (unbestätigt)" in lines(from_status)


def test_last_answer_hex_and_truncation():
    view = status_view(CONNECTED, report(value("battery", 75), raw=bytes.fromhex("1a044b1a0598")), now=NOW)
    assert "Letzte Antwort: 1a 04 4b 1a 05 98" in lines(view)
    long = status_view(CONNECTED, report(raw=bytes(range(60))), now=NOW)
    line = next(item for item in lines(long) if item.startswith("Letzte Antwort: "))
    assert line.endswith(" … (+12 Bytes)")
    assert line.startswith("Letzte Antwort: 00 01 02")
    none = status_view(CONNECTED, None, now=NOW)
    assert "Letzte Antwort: keine" in lines(none)


def test_detail_line_order():
    detail = lines(status_view(StateInfo("verbunden", "COM4", "alt"), full_report(), now=NOW, mac="001122334455"))
    idx = {prefix: next(i for i, line in enumerate(detail) if line.startswith(prefix))
           for prefix in ("Verbindung:", "Akku:", "Deckel:", "Band:", "Firmware:", "Seriennummer:", "Medium:",
                          "MAC:", "Transport:", "Letzte Antwort:", "Zuletzt abgefragt:", "Letzter Fehler:")}
    order = [idx[k] for k in ("Verbindung:", "Akku:", "Deckel:", "Band:", "Firmware:", "Seriennummer:",
                              "Medium:", "MAC:", "Transport:", "Letzte Antwort:", "Zuletzt abgefragt:",
                              "Letzter Fehler:")]
    assert order == sorted(order)
    assert detail[-1] == "Letzter Fehler: alt"


def test_low_battery_is_warning():
    view = status_view(CONNECTED, report(value("battery", 15)), now=NOW)
    assert view.chip == "P12 · verbunden (COM4) · Akku 15 %"
    assert view.role == "warning"


def test_open_lid_verified_is_warning_unverified_not_in_chip():
    view = status_view(CONNECTED, report(value("battery", 75), value("lid", "offen")), now=NOW)
    assert view.chip.endswith(" · Deckel offen")
    assert view.role == "warning"
    unverified = status_view(CONNECTED, report(value("lid", "offen", verified=False)), now=NOW)
    assert "Deckel" not in unverified.chip
    assert "Deckel: offen (unbestätigt)" in lines(unverified)


def test_unverified_values_never_in_chip():
    view = status_view(CONNECTED, report(value("battery", 60, verified=False),
                                         value("firmware", "1.0.6", verified=False)), now=NOW)
    assert view.chip == "P12 · verbunden (COM4)"
    assert "Akku: 60 % (unbestätigt)" in lines(view)
    assert "Firmware: 1.0.6 (unbestätigt)" in lines(view)
    assert "Seriennummer: nicht verfügbar" in lines(view)


def test_without_status():
    view = status_view(StateInfo("getrennt"), None, now=NOW)
    assert view.chip == "P12 · getrennt"
    assert view.role == "secondary"
    assert "Akku: nicht verfügbar" in lines(view)
    assert "Band: nicht verfügbar" in lines(view)
    assert "Zuletzt abgefragt: noch nie" in lines(view)
    assert view.tooltip == "getrennt · Status noch nie"


def test_paper_never_in_chip():
    view = status_view(CONNECTED, report(value("paper", "ok")), now=NOW)
    assert "Band" not in view.chip
    assert "Band: eingelegt gemeldet (leere Rolle nicht erkennbar)" in lines(view)
    empty = status_view(CONNECTED, report(value("paper", "leer")), now=NOW)
    assert "Band" not in empty.chip
    assert "Band: leer gemeldet (unbestätigt)" in lines(empty)


@pytest.mark.parametrize("state, chip, role", [
    (StateInfo("verbunden", "COM4", leased=True), "P12 · reserviert (Einrichtung)", "warning"),
    (StateInfo("offline"), "P12 · nicht erreichbar", "error"),
    (StateInfo("verbindet"), "P12 · verbindet …", "secondary"),
    (StateInfo("belegt"), "P12 · belegt", "warning"),
    (StateInfo("fehler", last_error="kaputt"), "P12 · Fehler", "error"),
])
def test_states(state, chip, role):
    view = status_view(state, None, now=NOW)
    assert view.chip == chip
    assert view.role == role


def test_offline_stays_error_with_low_battery():
    view = status_view(StateInfo("offline"), report(value("battery", 10)), now=NOW)
    assert view.role == "error"


def test_tooltip_is_short():
    state = StateInfo("verbunden", "ble:" + "X" * 200)
    view = status_view(state, full_report(), now=NOW)
    assert len(view.tooltip) <= 127


@pytest.mark.parametrize("delta, text", [
    (timedelta(seconds=0), "gerade eben"),
    (timedelta(seconds=59), "gerade eben"),
    (timedelta(seconds=60), "vor 1 min"),
    (timedelta(minutes=59, seconds=59), "vor 59 min"),
    (timedelta(hours=1), "vor 1 h"),
    (timedelta(hours=5, minutes=30), "vor 5 h"),
])
def test_age_text(delta, text):
    assert age_text(NOW - delta, NOW) == text
    assert age_text(None, NOW) == "noch nie"
