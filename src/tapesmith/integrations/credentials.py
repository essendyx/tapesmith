"""Secret-Referenzen für Tokens der Homelab-Dienste.

Formen: `keyring:<dienst>/<benutzer>` (Windows-Anmeldeinformationsspeicher über das Paket
`keyring`, erst beim Aufruf importiert), `file:<pfad>` (Textdatei, `%VAR%` und `~` werden
erweitert) und `env:<NAME>` (Umgebungsvariable). Ein Token erscheint nie in Meldungen.
Das Modul ist formatgleich zu `secretref`, damit es später darauf umgeleitet werden kann.
"""

from __future__ import annotations

import importlib
import os
import re
from collections.abc import Mapping

from tapesmith.integrations.errors import TokenMissing
from tapesmith.i18n import N_, _t

REF_PREFIXES = ("keyring:", "file:", "env:")

_ENV_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_ASSIGN_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([^=].*)$")
KEYRING_MISSING_HINT = N_("Paket keyring fehlt, Token als Datei hinterlegen")


def _keyring_parts(rest: str) -> tuple[str, str] | None:
    service, sep, user = rest.partition("/")
    if not sep or not service or not user:
        return None
    if service != service.strip() or user != user.strip():
        return None
    return service, user


def check_ref(ref: str) -> str:
    """Prüft die Form einer Secret-Referenz und gibt sie unverändert zurück (sonst ValueError)."""
    if not isinstance(ref, str):
        raise ValueError(_t("Secret-Referenz muss ein Text sein"))
    if ref.startswith("keyring:"):
        if _keyring_parts(ref[len("keyring:"):]) is None:
            raise ValueError(_t("Ungültige Secret-Referenz '{ref}' (Form keyring:<dienst>/<benutzer>)", ref=ref))
        return ref
    if ref.startswith("file:"):
        if not ref[len("file:"):].strip():
            raise ValueError(_t("Ungültige Secret-Referenz '{ref}' (Form file:<pfad>)", ref=ref))
        return ref
    if ref.startswith("env:"):
        if not _ENV_RE.match(ref[len("env:"):]):
            raise ValueError(_t("Ungültige Secret-Referenz '{ref}' (Form env:<NAME>)", ref=ref))
        return ref
    raise ValueError(_t("Ungültige Secret-Referenz '{ref}' (erlaubt: keyring:, file:, env:)", ref=ref))


def describe_ref(ref: str | None) -> str:
    """Lesbare Beschreibung der Referenz, ohne den Token selbst."""
    if not ref:
        return _t("nicht gesetzt")
    kind, _, rest = ref.partition(":")
    if kind == "keyring":
        return _t("Windows-Anmeldeinformationen {rest}", rest=rest)
    if kind == "file":
        return _t("Datei {rest}", rest=rest)
    if kind == "env":
        return _t("Umgebungsvariable {rest}", rest=rest)
    return _t("ungültige Referenz '{ref}'", ref=ref)


def _load_keyring(keyring_module):
    if keyring_module is not None:
        return keyring_module
    return importlib.import_module("keyring")


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1].strip()
    return value


def _value_from_text(text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = _ASSIGN_RE.match(line)
        if match:
            line = match.group(2).strip()
        return _strip_quotes(line)
    return ""


def _read_file(ref: str, what: str) -> str:
    path = os.path.expanduser(os.path.expandvars(ref[len("file:"):].strip()))
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except OSError as exc:
        raise TokenMissing(what, ref) from exc
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise TokenMissing(what, ref, hint=_t("Datei {path} muss UTF-8 sein (eine Zeile, nur das Token)", path=path)) from exc
    return _value_from_text(text)


def read_secret(ref: str | None, *, what: str, keyring_module=None,
                environ: Mapping[str, str] | None = None) -> str:
    """Liest den Token zur Referenz `ref`. Fehlt er, `TokenMissing` mit Hinweis."""
    if not ref:
        raise TokenMissing(what, None)
    try:
        check_ref(ref)
    except ValueError as exc:
        raise TokenMissing(what, ref, hint=str(exc)) from exc

    if ref.startswith("file:"):
        value = _read_file(ref, what)
    elif ref.startswith("env:"):
        env = os.environ if environ is None else environ
        value = (env.get(ref[len("env:"):]) or "").strip()
    else:
        service, user = _keyring_parts(ref[len("keyring:"):])
        try:
            module = _load_keyring(keyring_module)
        except ImportError as exc:
            raise TokenMissing(what, ref, hint=_t(KEYRING_MISSING_HINT)) from exc
        try:
            value = (module.get_password(service, user) or "").strip()
        except Exception as exc:  # noqa: BLE001 (Fehler des Keyring-Backends)
            raise TokenMissing(what, ref, hint=_t("Windows-Anmeldeinformationen nicht lesbar ({name})", name=type(exc).__name__)) from exc

    if not value:
        raise TokenMissing(what, ref)
    return value


def has_secret(ref: str | None, **kw) -> bool:
    """Ob zur Referenz ein nicht leerer Token vorhanden ist (liest ihn, gibt ihn aber nie heraus)."""
    try:
        read_secret(ref, what=_t("Prüfung"), **kw)
    except TokenMissing:
        return False
    return True


def write_secret(ref: str, value: str, *, keyring_module=None) -> None:
    """Speichert `value` unter einer `keyring:`-Referenz im Windows-Anmeldeinformationsspeicher."""
    check_ref(ref)
    if not ref.startswith("keyring:"):
        raise ValueError(_t("Nur keyring:-Referenzen lassen sich aus der App setzen"))
    if not value or not value.strip():
        raise ValueError(_t("Leerer Token wird nicht gespeichert"))
    service, user = _keyring_parts(ref[len("keyring:"):])
    try:
        module = _load_keyring(keyring_module)
    except ImportError as exc:
        raise ValueError(_t("{keyring_missing_hint} (Token lässt sich nicht speichern)", keyring_missing_hint=_t(KEYRING_MISSING_HINT))) from exc
    module.set_password(service, user, value.strip())
