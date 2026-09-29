"""Einheitliche Fehlerklassen der Homelab-Integrationen.

Jede Klasse trägt den HTTP-Status für die Web-API und den Exit-Code für die CLI. `str(exc)` ist
immer `"{service}: {message}"`; `hint` ist eine Handlungsanweisung auf Deutsch.
"""

from __future__ import annotations

from tapesmith.errors import EXIT_ERROR, EXIT_UNREACHABLE
from tapesmith.i18n import _t


class IntegrationError(RuntimeError):
    """Basisklasse: Fehler beim Zugriff auf einen Homelab-Dienst."""

    http_status: int = 502
    exit_code: int = EXIT_ERROR

    def __init__(self, service: str, message: str, *, hint: str = ""):
        super().__init__(f"{service}: {message}")
        self.service = service
        self.message = message
        self.hint = hint

    def __str__(self) -> str:
        return f"{self.service}: {self.message}"


def _token_hint(ref: str | None) -> str:
    """Handlungsanweisung, wie das Token zur Referenz `ref` hinterlegt wird."""
    import os

    if not ref:
        return _t("In homelab.json eine token_ref eintragen")
    kind, _, rest = ref.partition(":")
    if kind == "file":
        path = os.path.expanduser(os.path.expandvars(rest.strip()))
        return _t("Token als Datei {path} ablegen (eine Zeile, nur das Token)", path=path)
    if kind == "keyring":
        return (_t("Token mit p12 homelab secret {strip} im Windows-Anmeldeinformationsspeicher hinterlegen", strip=rest.strip()))
    if kind == "env":
        return _t("Umgebungsvariable {strip} setzen", strip=rest.strip())
    return _t("In homelab.json eine gültige token_ref eintragen")


class TokenMissing(IntegrationError):
    """Token fehlt oder ist nicht lesbar: Meldung "Token fehlt: <was> (<Referenz>)"."""

    http_status = 424
    exit_code = EXIT_ERROR

    def __init__(self, what: str, ref: str | None, *, hint: str | None = None):
        from tapesmith.integrations.credentials import describe_ref

        super().__init__(_t("Zugangsdaten"), _t("Token fehlt: {what} ({describe_ref})", what=what, describe_ref=describe_ref(ref)),
                         hint=_token_hint(ref) if hint is None else hint)
        self.what = what
        self.ref = ref


class NotConfigured(IntegrationError):
    """Dienst ist in homelab.json nicht eingerichtet."""

    http_status = 424
    exit_code = EXIT_ERROR


class NotReachable(IntegrationError):
    """Dienst antwortet nicht (Verbindung abgelehnt, Zeitüberschreitung)."""

    http_status = 503
    exit_code = EXIT_UNREACHABLE


class AuthFailed(IntegrationError):
    """Dienst lehnt den Zugriff ab (HTTP 401/403)."""

    http_status = 502
    exit_code = EXIT_ERROR


class UpstreamError(IntegrationError):
    """Sonstige Fehlerantwort oder unlesbare Antwort des Dienstes."""

    http_status = 502
    exit_code = EXIT_ERROR


def exit_code(exc: BaseException) -> int:
    """Exit-Code für die CLI: `IntegrationError.exit_code`, sonst 1."""
    if isinstance(exc, IntegrationError):
        return exc.exit_code
    return EXIT_ERROR
