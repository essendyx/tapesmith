"""Klartext-Fehler mit Handlungsanweisung statt Tracebacks.

Jede `Advice` trägt zusätzlich einen stabilen Fehlercode aus `ERROR_CODES`. `error_code(exc)`
liefert ihn für eine beliebige Ausnahme; die Web-API schreibt ihn in
das Feld `code` jeder Fehlerantwort, die Oberfläche übersetzt Titel und Hinweis darüber.
"""

import re
from dataclasses import dataclass

from tapesmith.fileutil import FileLockTimeout
from tapesmith.jobs import IncompletePrint
from tapesmith.lock import PrinterBusy
from tapesmith.render.fonts import FontMissing
from tapesmith.render.zxing import DecoderUnavailable
from tapesmith.templates.model import TemplateError
from tapesmith.transport.base import ConnectTimeout, TransportError
from tapesmith.i18n import _t

EXIT_OK, EXIT_ERROR, EXIT_UNREACHABLE, EXIT_TEMPLATE, EXIT_BUSY = 0, 1, 5, 6, 7

_COM_PORT = re.compile(r"COM\d+", re.IGNORECASE)


# Stabile Fehlercodes (`client.*` gibt es nur im Web-Client).
ERROR_CODES: tuple[str, ...] = (
    "printer.busy", "file.locked", "print.incomplete", "printer.unreachable",
    "port.busy", "port.missing", "bluetooth.lost", "printer.not_paired", "transport.error",
    "ipc.error", "template.invalid", "document.invalid", "protocol.error", "font.missing",
    "secret.missing", "label.not_printable", "value.invalid", "request.invalid", "not_found",
    "auth.required", "auth.forbidden", "method.not_allowed", "conflict", "too_large", "rate_limited",
    "http.error",
    "integration.token_missing", "integration.not_configured", "integration.unreachable",
    "integration.auth_failed", "integration.upstream",
    "update.not_installed", "update.no_trusted_key", "update.source_invalid",
    "update.source_unreachable", "update.signature_invalid", "update.checksum_mismatch",
    "update.download_failed", "update.busy", "update.apply_failed",
    "decoder.unavailable", "module.disabled",
    "aborted", "internal",
)

# HTTP-Status je Code (ohne `http.error`, dessen Status die Antwort selbst setzt).
CODE_STATUS: dict[str, int] = {
    "printer.busy": 409, "file.locked": 409, "print.incomplete": 503, "printer.unreachable": 503,
    "port.busy": 503, "port.missing": 503, "bluetooth.lost": 503, "printer.not_paired": 503,
    "transport.error": 503, "ipc.error": 503, "template.invalid": 422, "document.invalid": 422,
    "protocol.error": 422, "font.missing": 500, "secret.missing": 422, "label.not_printable": 422,
    "value.invalid": 422, "request.invalid": 422, "not_found": 404, "auth.required": 401,
    "auth.forbidden": 403, "method.not_allowed": 405, "conflict": 409, "too_large": 413,
    "rate_limited": 429, "integration.token_missing": 424, "integration.not_configured": 424,
    "integration.unreachable": 503, "integration.auth_failed": 502, "integration.upstream": 502,
    "update.not_installed": 409, "update.no_trusted_key": 409,
    "update.source_invalid": 422, "update.source_unreachable": 503, "update.signature_invalid": 502,
    "update.checksum_mismatch": 502, "update.download_failed": 502, "update.busy": 409,
    "update.apply_failed": 500, "decoder.unavailable": 503, "module.disabled": 409, "aborted": 500,
    "internal": 500,
}

_CODE_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$")


@dataclass(frozen=True)
class Advice:
    title: str
    hint: str
    exit_code: int
    code: str


def _text(exc: BaseException) -> str:
    parts = [str(exc)]
    if exc.__cause__ is not None:
        parts.append(str(exc.__cause__))
    return " ".join(parts)


def _contains(text: str, *needles: str) -> bool:
    lowered = text.lower()
    return any(needle.lower() in lowered for needle in needles)


def _transport_advice(text: str) -> Advice:
    if _contains(text, "zugriff verweigert", "access is denied", "permissionerror", "errno 13"):
        match = _COM_PORT.search(text)
        title = _t("{port} belegt", port=match.group(0).upper()) if match else _t("COM-Port belegt")
        return Advice(
            title,
            _t("Ein anderes Programm hält den Port (Handy-App, altes phomemo-Tool, Terminal). Programm schließen oder Drucker aus- und einschalten."),
            EXIT_BUSY,
            "port.busy",
        )
    if _contains(text, "filenotfound", "kann die angegebene datei nicht finden",
                 "cannot find the file", "could not open port"):
        return Advice(
            _t("COM-Port fehlt"),
            _t("Drucker in Windows unter Bluetooth koppeln oder 'p12 setup' ausführen."),
            EXIT_UNREACHABLE,
            "port.missing",
        )
    if _contains(text, "semaphore", "winerror 121"):
        return Advice(
            _t("Bluetooth-Verbindung abgebrochen"),
            _t("Drucker aus oder außer Reichweite. Einschalten, näher heran und erneut versuchen."),
            EXIT_UNREACHABLE,
            "bluetooth.lost",
        )
    if _contains(text, "kein ausgehender bluetooth-com-port", "no outgoing bluetooth com port"):
        return Advice(
            _t("Drucker nicht gekoppelt"),
            _t("Drucker in Windows unter Bluetooth koppeln, dann 'p12 setup'."),
            EXIT_UNREACHABLE,
            "printer.not_paired",
        )
    return Advice(_t("Verbindungsfehler"), _t("'p12 doctor' ausführen."), EXIT_UNREACHABLE, "transport.error")


def explain(exc: BaseException) -> Advice:
    """Ordnet einer Ausnahme einen Klartext-Titel, eine Handlungsanweisung und einen Exit-Code zu."""
    if isinstance(exc, PrinterBusy):
        return Advice(
            _t("Drucker belegt"),
            _t("Ein anderes P12-Programm druckt gerade. Kurz warten oder das andere Programm beenden."),
            EXIT_BUSY,
            "printer.busy",
        )
    if isinstance(exc, FileLockTimeout):
        return Advice(
            _t("Datei gesperrt"),
            _t("Ein anderes P12-Programm schreibt gerade. Kurz warten und erneut versuchen."),
            EXIT_BUSY,
            "file.locked",
        )
    if isinstance(exc, IncompletePrint):
        return Advice(
            _t("Druck unvollständig"),
            _t("Verbindung während des Drucks verloren (Akku leer? Drucker aus?). Drucker prüfen und das Label erneut drucken (p12 reprint last)."),
            EXIT_UNREACHABLE,
            "print.incomplete",
        )
    if isinstance(exc, ConnectTimeout):
        return Advice(
            _t("Drucker nicht erreichbar"),
            _t("Drucker aus oder eingeschlafen? Einschalten. Handy-App verbunden? Nur ein Host gleichzeitig, dort trennen."),
            EXIT_UNREACHABLE,
            "printer.unreachable",
        )
    if isinstance(exc, TransportError):
        advice = _transport_advice(_text(exc))
        code = _own_code(exc) or _ipc_code(exc)
        if code is not None:
            advice = Advice(advice.title, advice.hint, advice.exit_code, code)
        return advice
    if isinstance(exc, TemplateError):
        return Advice(_t("Vorlage oder Variable ungültig"), _t("'p12 template show <name>' zeigt die Felder."),
                      EXIT_TEMPLATE, "template.invalid")
    if isinstance(exc, FontMissing):
        return Advice(_t("Schrift fehlt"), _t("Installation prüfen (tools/fetch_fonts.py)."), EXIT_ERROR,
                      "font.missing")
    if isinstance(exc, DecoderUnavailable):
        return Advice(_t("Barcode-Decoder nicht verfügbar"),
                      _t("zxing-cpp ließ sich nicht laden (z. B. von Windows Smart App Control blockiert). Seriennummer von Hand eingeben; Drucken funktioniert weiter."),
                      EXIT_ERROR, "decoder.unavailable")
    if isinstance(exc, (KeyboardInterrupt, EOFError)):
        return Advice(_t("Abgebrochen"), "", EXIT_ERROR, "aborted")
    if _own_code(exc) == "module.disabled":
        return Advice(_t("Modul ausgeschaltet"), _t("Einschalten unter Einstellungen > Module oder mit 'tapesmith module enable <modul>'."), EXIT_ERROR, "module.disabled")
    return Advice(_t("Fehler"), "", EXIT_ERROR, error_code(exc))


def _own_code(exc: BaseException) -> str | None:
    """Eigener Code der Ausnahme (Attribut `code` an Instanz oder Klasse), falls es ein Text in
    Code-Form ist (klein, mit Punkten). So liefern `UpdateError` und spätere Ausnahmen
    ihren Code selbst."""
    code = getattr(exc, "code", None)
    if isinstance(code, str) and _CODE_RE.match(code):
        return code
    return None


def _mro_names(exc: BaseException) -> set[str]:
    return {cls.__name__ for cls in type(exc).__mro__}


def _ipc_code(exc: BaseException) -> str | None:
    # spät importiert: tapesmith.ipc.protocol baut auf dem Transport-Paket auf
    from tapesmith.ipc.protocol import IpcError, ProtocolError

    if isinstance(exc, ProtocolError):
        return "protocol.error"
    if isinstance(exc, IpcError):
        return "ipc.error"
    return None


def _integration_code(exc: BaseException) -> str | None:
    # spät importiert: tapesmith.integrations.errors importiert dieses Modul (Exit-Codes)
    from tapesmith.integrations import errors as ierr

    if not isinstance(exc, ierr.IntegrationError):
        return None
    for cls, code in ((ierr.TokenMissing, "integration.token_missing"),
                      (ierr.NotConfigured, "integration.not_configured"),
                      (ierr.NotReachable, "integration.unreachable"),
                      (ierr.AuthFailed, "integration.auth_failed")):
        if isinstance(exc, cls):
            return code
    return "integration.upstream"


_HTTP_STATUS_CODES = {401: "auth.required", 403: "auth.forbidden", 404: "not_found",
                      405: "method.not_allowed", 409: "conflict", 413: "too_large", 422: "request.invalid",
                      429: "rate_limited"}


def http_status_code(status: int) -> str:
    """Fehlercode zu einem HTTP-Status ohne eigene Ausnahme (sonst `http.error`)."""
    return _HTTP_STATUS_CODES.get(status, "http.error")


def error_code(exc: BaseException) -> str:
    """Stabiler Fehlercode für `exc`.

    Reihenfolge: eigenes Attribut `code` (Text in Code-Form), dann die Tabelle über `isinstance`.
    Speziellere Klassen stehen dabei vor ihren Basisklassen (`ProtocolError` vor `IpcError` vor
    `TransportError`, `SecretMissing` und `LabelNotPrintable` vor `ValueError`, `NotFound` vor
    `KeyError`). Web-Typen (`NotFound`, `LabelNotPrintable`, `RequestValidationError`,
    `HTTPException`) werden über den Klassennamen in der MRO erkannt, damit dieses Modul keine
    Web-Abhängigkeit bekommt."""
    own = _own_code(exc)
    if own is not None:
        return own
    names = _mro_names(exc)
    if isinstance(exc, PrinterBusy):
        return "printer.busy"
    if isinstance(exc, FileLockTimeout):
        return "file.locked"
    if isinstance(exc, IncompletePrint):
        return "print.incomplete"
    if isinstance(exc, ConnectTimeout):
        return "printer.unreachable"
    if isinstance(exc, TransportError):
        return _ipc_code(exc) or _transport_advice(_text(exc)).code
    if isinstance(exc, TemplateError):
        return "template.invalid"
    from tapesmith.document.model import DocumentError  # spät: vermeidet Importzyklen

    if isinstance(exc, DocumentError):
        return "document.invalid"
    if isinstance(exc, FontMissing):
        return "font.missing"
    from tapesmith.secretref import SecretMissing

    if isinstance(exc, SecretMissing):
        return "secret.missing"
    if "LabelNotPrintable" in names:
        return "label.not_printable"
    if "RequestValidationError" in names:
        return "request.invalid"
    if "NotFound" in names:
        return "not_found"
    if isinstance(exc, (ValueError, KeyError)):
        return "value.invalid"
    if "HTTPException" in names:
        status = getattr(exc, "status_code", None)
        return http_status_code(status) if isinstance(status, int) else "http.error"
    integration = _integration_code(exc)
    if integration is not None:
        return integration
    if isinstance(exc, (KeyboardInterrupt, EOFError)):
        return "aborted"
    return "internal"


def format_advice(exc: BaseException, advice: Advice | None = None) -> str:
    advice = advice if advice is not None else explain(exc)
    text = _t("Fehler: {title} ({exc})", title=advice.title, exc=exc)
    if advice.hint:
        text += f"\n  -> {advice.hint}"
    return text
