"""Test für die HCI-Snoop-Anleitung."""

from pathlib import Path

DOC = Path(__file__).parent.parent / "docs" / "hardware" / "hci-snoop.md"

HEADINGS = (
    "## Voraussetzungen",
    "## Mitschnitt aufnehmen",
    "## Datei holen",
    "## Auswerten",
    "## Vergleich mit dem Hex-Log",
    "## Ergebnis eintragen",
    "## Datenschutz",
)


def test_doc_exists_with_all_headings_and_terms():
    assert DOC.exists()
    text = DOC.read_text(encoding="utf-8")
    for heading in HEADINGS:
        assert heading in text
    for term in ("btsnoop_hci.log", "adb bugreport", "1B 4E 04", "1B 37"):
        assert term in text
