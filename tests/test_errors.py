import pytest

from tapesmith.errors import explain, format_advice
from tapesmith.fileutil import FileLockTimeout
from tapesmith.jobs import IncompletePrint
from tapesmith.lock import PrinterBusy
from tapesmith.render.fonts import FontMissing
from tapesmith.templates.model import TemplateError
from tapesmith.transport.base import ConnectTimeout, TransportError


class PrinterOffline(ConnectTimeout):
    """Steht für eine Unterklasse, die ebenfalls als 'nicht erreichbar' gelten soll."""


@pytest.mark.parametrize(
    "exc, exit_code, title_contains",
    [
        (PrinterBusy("belegt"), 7, "Drucker belegt"),
        (IncompletePrint("x", 3, 9), 5, "Druck unvollständig"),
        (ConnectTimeout("COM4: keine Verbindung nach 8 s"), 5, "nicht erreichbar"),
        (PrinterOffline("COM4: keine Verbindung nach 8 s"), 5, "nicht erreichbar"),
        (
            TransportError(
                "COM4: could not open port 'COM4': "
                "PermissionError(13, 'Zugriff verweigert', None, 5)"
            ),
            7,
            "COM4 belegt",
        ),
        (
            TransportError(
                "COM7: could not open port 'COM7': "
                "FileNotFoundError(2, 'Das System kann die angegebene Datei nicht finden.', None, 2)"
            ),
            5,
            "COM-Port fehlt",
        ),
        (
            TransportError(
                "COM4: Schreiben fehlgeschlagen: WriteFile failed "
                "(OSError(22, 'Das Zeitlimit für die Semaphore wurde erreicht.', None, 121))"
            ),
            5,
            "Bluetooth-Verbindung abgebrochen",
        ),
        (
            TransportError("Kein ausgehender Bluetooth-COM-Port für 001122334455. Drucker gekoppelt?"),
            5,
            "Drucker nicht gekoppelt",
        ),
        (TemplateError("kaputt"), 6, "Vorlage oder Variable ungültig"),
        (FontMissing("weg"), 1, "Schrift fehlt"),
        (ValueError("kaputt"), 1, "Fehler"),
    ],
)
def test_explain_maps_exception_to_advice(exc, exit_code, title_contains):
    advice = explain(exc)
    assert advice.exit_code == exit_code
    assert title_contains in advice.title


def test_explain_prefers_more_specific_transport_advice_over_generic():
    exc = TransportError("sonst nichts Bekanntes")
    advice = explain(exc)
    assert advice.title == "Verbindungsfehler"
    assert advice.exit_code == 5


def test_connect_timeout_hint_mentions_single_host():
    advice = explain(ConnectTimeout("COM4: keine Verbindung nach 8 s"))
    assert "Nur ein Host gleichzeitig" in advice.hint


def test_cause_only_permission_error_is_detected():
    try:
        try:
            raise PermissionError(13, "Access is denied")
        except PermissionError as cause:
            raise TransportError("x") from cause
    except TransportError as exc:
        advice = explain(exc)
    assert "belegt" in advice.title
    assert advice.exit_code == 7


def test_keyboard_interrupt_and_eof_are_exit_1_with_no_hint():
    for exc in (KeyboardInterrupt(), EOFError()):
        advice = explain(exc)
        assert advice.exit_code == 1
        assert advice.title == "Abgebrochen"
        assert advice.hint == ""


def test_format_advice_layout():
    text = format_advice(ConnectTimeout("COM4: keine Verbindung nach 8 s"))
    assert text.startswith("Fehler: Drucker nicht erreichbar (COM4")
    assert "\n  -> Drucker aus" in text


def test_format_advice_without_hint_has_no_arrow_line():
    text = format_advice(ValueError("kaputt"))
    assert text == "Fehler: Fehler (kaputt)"
    assert "->" not in text
