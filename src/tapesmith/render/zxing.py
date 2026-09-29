"""Zentraler, optionaler Zugriff auf zxing-cpp (Barcode-Decoder).

zxing-cpp ist eine native Erweiterung (.pyd). Windows Smart App Control kann sie im gebauten
Programm blockieren ("DLL load failed ... Anwendungssteuerungsrichtlinie"). Deshalb importiert
kein Modul zxing-cpp auf Modulebene: der Import passiert erst hier beim ersten Bedarf, ein
Fehlschlag (ImportError/OSError) wird samt Grund gemerkt. Erzeugt werden alle Codes ohne
zxing-cpp (Code128 über `render.code128`, QR über segno, DataMatrix über ppf-datamatrix); nur das
Rücklesen (Selbsttest der Codes) und der SN-Scan aus Fotos brauchen den Decoder.
"""

from __future__ import annotations

import importlib
import threading
from types import ModuleType
from tapesmith.i18n import N_, _t

MODULE_NAME = "zxingcpp"
NOT_READ_WARNING = N_("Code nicht rückgelesen: Decoder nicht verfügbar")


class DecoderUnavailable(RuntimeError):
    """zxing-cpp lässt sich nicht laden. Fehlercode `decoder.unavailable` (errors.ERROR_CODES)."""

    code = "decoder.unavailable"


_lock = threading.Lock()
_state: dict = {"loaded": False, "module": None, "reason": ""}


def _load() -> ModuleType | None:
    with _lock:
        if not _state["loaded"]:
            try:
                _state["module"] = importlib.import_module(MODULE_NAME)
                _state["reason"] = ""
            except (ImportError, OSError) as exc:
                _state["module"] = None
                _state["reason"] = f"{type(exc).__name__}: {exc}"
            _state["loaded"] = True
        return _state["module"]


def reset() -> None:
    """Vergisst das Ladeergebnis (für Tests); der nächste Zugriff versucht den Import erneut."""
    with _lock:
        _state.update(loaded=False, module=None, reason="")


def available() -> bool:
    return _load() is not None


def reason() -> str:
    """Grund, warum zxing-cpp fehlt (leer, wenn es geladen ist)."""
    _load()
    return _state["reason"]


def status_text() -> str:
    """Einzeiliger Status für Selbsttest, Diagnose und Support-Bericht."""
    module = _load()
    if module is not None:
        version = getattr(module, "__version__", "")
        return _t("zxing-cpp geladen{value}", value=f' ({version})' if version else '')
    return _t("nicht verfügbar ({reason}), Codes werden nicht rückgelesen, SN-Scan aus", reason=_state['reason'])


def require() -> ModuleType:
    """Das zxingcpp-Modul oder `DecoderUnavailable` mit Grund."""
    module = _load()
    if module is None:
        raise DecoderUnavailable(_t("Barcode-Decoder nicht verfügbar: {reason}", reason=_state['reason']))
    return module


def barcode_format(fmt):
    """`zxingcpp.BarcodeFormat` zu einem Formatnamen ("Code128", "DataMatrix", "QRCode");
    ein schon fertiges Format wird durchgereicht."""
    if isinstance(fmt, str):
        return getattr(require().BarcodeFormat, fmt)
    return fmt
