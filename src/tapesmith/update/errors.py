"""Fehler des Updaters mit stabilem Code (`update.*`) und passendem HTTP-Status."""

from __future__ import annotations

from tapesmith.errors import CODE_STATUS
from tapesmith.i18n import _t

UPDATE_CODES: tuple[str, ...] = tuple(code for code in CODE_STATUS if code.startswith("update."))


class UpdateError(RuntimeError):
    """`UpdateError(code, message, hint="")`: `code` stammt aus `errors.CODE_STATUS`, `http_status` folgt ihm.

    `tapesmith.errors.error_code` liest das Attribut `code`, die Web-API zusätzlich `http_status`
    und `hint`."""

    def __init__(self, code: str, message: str, *, hint: str = ""):
        if code not in UPDATE_CODES:
            raise ValueError(_t("Unbekannter Update-Fehlercode: {code}", code=code))
        super().__init__(message)
        self.code = code
        self.hint = hint
        self.http_status = CODE_STATUS[code]
