import json

from tapesmith.device.profile import load_profile
from tapesmith.printer import PrinterSession
from tapesmith.transport.base import MemoryTransport, TransportError
from tapesmith.verify import Verifier, VerifyReport


def test_full_run_records_results_and_calibration(tmp_path):
    responses = {
        bytes.fromhex("1f1107"): bytes.fromhex("1a07010203"),
        bytes.fromhex("1f1108"): bytes.fromhex("1a0450"),
        bytes.fromhex("1f1112"): bytes.fromhex("1a0598"),   # P12: 98 = Deckel zu (invertiert, Befund b)
    }
    transports = []

    def open_session(profile):
        t = MemoryTransport(responses)
        transports.append(t)
        return PrinterSession(t, profile, sleep=lambda s: None)

    answers = iter(["", "", "8", "88", "j", "99", "7.5", "8.5", "n"])
    said = []
    cal = tmp_path / "calibration.json"
    report = Verifier(open_session, load_profile(), cal, ask=lambda q: next(answers), say=said.append).run()

    assert report.firmware == "1.2.3"
    r = report.results
    assert r["responds"] is True
    assert r["battery"]["decoded"] == ["Akku 80 %"]
    assert r["lid_closed"]["decoded"] == ["Deckel zu"]
    assert r["edge"] == {"first_row": 8, "last_row": 88, "content_offset": 8, "content_dots": 84}
    assert r["edge_complete"] is True
    assert r["ruler"] == {"measured_mm": 99.0, "leader_mm": 7.5, "trailer_mm": 8.5, "length_factor": 100 / 99}
    assert r["ruler_complete"] is False
    assert json.loads(cal.read_text(encoding="utf-8")) == {
        "content_offset": 8, "content_dots": 84, "length_factor": 100 / 99, "leader_mm": 7.5, "trailer_mm": 8.5}
    assert len(transports) == 3                       # Abfragen, Kantentest, Lineal
    assert json.loads(report.to_json())["firmware"] == "1.2.3"


def test_edge_span_too_small_is_asked_again(tmp_path):
    def open_session(profile):
        return PrinterSession(MemoryTransport(), profile, sleep=lambda s: None)

    answers = iter(["", "", "0", "0", "0", "44", "j", "100", "8", "8", "n"])
    said = []
    report = Verifier(open_session, load_profile(), tmp_path / "c.json",
                      ask=lambda q: next(answers), say=said.append).run()
    assert report.results["edge"]["first_row"] == 0
    assert report.results["edge"]["last_row"] == 44
    assert any("mind." in s for s in said)


def test_report_marked_complete_after_full_run(tmp_path):
    def open_session(profile):
        return PrinterSession(MemoryTransport(), profile, sleep=lambda s: None)

    answers = iter(["", "", "8", "88", "j", "99", "7.5", "8.5", "n"])
    verifier = Verifier(open_session, load_profile(), tmp_path / "c.json",
                        ask=lambda q: next(answers), say=lambda s: None)
    report = verifier.run()
    assert report.complete is True
    assert verifier.report is report          # Verifier haelt den Bericht als Instanzattribut


def test_open_session_retries_once_after_transport_error(tmp_path):
    calls = []

    def open_session(profile):
        calls.append(profile)
        if len(calls) == 1:
            raise TransportError("nicht bereit")
        return PrinterSession(MemoryTransport({
            bytes.fromhex("1f1107"): bytes.fromhex("1a07010203"),
        }), profile, sleep=lambda s: None)

    sleeps = []
    answers = iter(["", "", "8", "88", "j", "99", "7.5", "8.5", "n"])
    verifier = Verifier(open_session, load_profile(), tmp_path / "c.json",
                        ask=lambda q: next(answers), say=lambda s: None,
                        sleep=sleeps.append)
    report = verifier.run()

    assert sleeps == [1.5]
    assert len(calls) == 4                     # 1 Fehlversuch + 1 Wiederholung + 2 weitere Sitzungen
    assert report.complete is True


def test_transport_error_after_retry_leaves_partial_report(tmp_path):
    def open_session(profile):
        raise TransportError("Drucker weg")

    verifier = Verifier(open_session, load_profile(), tmp_path / "c.json",
                        ask=lambda q: "", say=lambda s: None, sleep=lambda s: None)
    try:
        verifier.run()
        assert False, "sollte TransportError werfen"
    except TransportError:
        pass
    assert verifier.report.complete is False
    assert verifier.report.results == {}


def test_invalid_numbers_are_asked_again(tmp_path):
    def open_session(profile):
        return PrinterSession(MemoryTransport(), profile, sleep=lambda s: None)

    answers = iter(["", "", "x", "8", "200", "88", "j", "abc", "100", "8", "8", "j"])
    report = Verifier(open_session, load_profile(), tmp_path / "c.json",
                      ask=lambda q: next(answers), say=lambda s: None).run()
    assert report.results["edge"]["first_row"] == 8
    assert report.results["edge"]["last_row"] == 88
    assert report.results["responds"] is False
    assert report.firmware is None


def test_lid_status_uses_p12_device_codes(tmp_path):
    """Beim P12 ist der Deckelcode invertiert (Gerätebefund b): 1a0599 heißt Deckel offen."""
    responses = {bytes.fromhex("1f1112"): bytes.fromhex("1a0599")}

    def open_session(profile):
        return PrinterSession(MemoryTransport(responses), profile, sleep=lambda s: None)

    answers = iter(["", "", "8", "88", "j", "99", "7.5", "8.5", "n"])
    report = Verifier(open_session, load_profile(), tmp_path / "c.json",
                      ask=lambda q: next(answers), say=lambda s: None).run()
    assert report.results["lid_open"]["decoded"] == ["Deckel offen"]
    assert report.results["lid_closed"]["decoded"] == ["Deckel offen"]
