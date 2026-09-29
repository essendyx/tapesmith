"""Kein " - " als Gedankenstrich-Ersatz in Kommentaren der Automatisierungs- und Hotkey-Module
(auch nicht als Bindestrich mit Leerzeichen im Fliesstext).

Bindestriche in Woertern und Minuszeichen in Code/Zahlen bleiben erlaubt: geprueft wird nur der
Kommentarteil ab dem ersten "#" je Zeile.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

FILES = (
    "src/tapesmith/automation/hotfolder.py",
    "src/tapesmith/automation/telegram.py",
    "src/tapesmith/automation/mqtt.py",
    "src/tapesmith/cli_cmds/hotfolder.py",
    "src/tapesmith/gui/hotkey.py",
    "src/tapesmith/hotkeyspec.py",
)


@pytest.mark.parametrize("relpath", FILES)
def test_keine_gedankenstrich_ersatz_in_kommentaren(relpath):
    text = (ROOT / relpath).read_text(encoding="utf-8")
    for lineno, line in enumerate(text.splitlines(), start=1):
        idx = line.find("#")
        if idx == -1:
            continue
        comment = line[idx:]
        assert " - " not in comment, f"{relpath}:{lineno}: Gedankenstrich-Ersatz: {line!r}"
