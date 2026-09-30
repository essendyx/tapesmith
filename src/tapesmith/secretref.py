"""Secret-Referenzen: `keyring:<dienst>/<benutzer>`, `file:<pfad>`, `env:<NAME>`.

Werte selbst landen nie im Repo oder in `config.json`: nur die Referenz auf den Ort, an dem der
Wert zur Laufzeit liegt (Windows-Anmeldeinformationen, eine Datei, eine Umgebungsvariable). Dieses
Modul liest (und für `keyring:` schreibt) den Wert; der Wert selbst erscheint nie in einer
Meldung, einem Log oder einem `repr`.
"""

import os
import re
from pathlib import Path
from tapesmith.i18n import N_, _t

REF_PREFIXES = ("keyring:", "file:", "env:")

_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_FILE_LINE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_INVALID_MESSAGE = (
    N_("Secret-Referenz ungültig: erlaubt keyring:<dienst>/<benutzer>, file:<pfad>, env:<NAME>"))


class SecretMissing(ValueError):
    """Referenz ist gültig, aber es liegt (noch) kein Wert vor. Die Meldung nennt nie den Wert."""


def is_ref(value) -> bool:
    """Ob `value` ein Text mit einem der `REF_PREFIXES` ist."""
    return isinstance(value, str) and value.startswith(REF_PREFIXES)


def _split_keyring(ref: str) -> tuple[str, str]:
    rest = ref[len("keyring:"):]
    service, sep, user = rest.partition("/")
    if not sep or not service or not user or service != service.strip() or user != user.strip():
        raise ValueError(_t(_INVALID_MESSAGE))
    return service, user


def check_ref(value: str) -> str:
    """Prüft die Form einer Secret-Referenz und gibt sie unverändert zurück.

    `keyring:<dienst>/<benutzer>` (beide nicht leer, kein Leerzeichen am Rand), `file:<pfad>`
    (nicht leer), `env:<NAME>` (`^[A-Za-z_][A-Za-z0-9_]*$`). Sonst `ValueError`.
    """
    if not isinstance(value, str):
        raise ValueError(_t(_INVALID_MESSAGE))
    if value.startswith("keyring:"):
        _split_keyring(value)
        return value
    if value.startswith("file:"):
        path = value[len("file:"):]
        if not path.strip():
            raise ValueError(_t(_INVALID_MESSAGE))
        return value
    if value.startswith("env:"):
        name = value[len("env:"):]
        if not _ENV_NAME_RE.match(name):
            raise ValueError(_t(_INVALID_MESSAGE))
        return value
    raise ValueError(_t(_INVALID_MESSAGE))


def _import_keyring():
    try:
        import keyring
    except ImportError:
        raise SecretMissing(_t("Paket keyring fehlt: pip install keyring")) from None
    return keyring


def _first_value_from_file(text: str) -> str:
    """Erste nicht leere Zeile, die nicht mit '#' beginnt. Form NAME=WERT (NAME wie eine
    Umgebungsvariable) liefert WERT; umschließende Anführungszeichen werden entfernt."""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        name, sep, rest = stripped.partition("=")
        if sep and _FILE_LINE_NAME_RE.match(name):
            value = rest.strip()
        else:
            value = stripped
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        return value
    return ""


def read_secret(ref: str, *, keyring_module=None, environ=None) -> str:
    """Liest den Wert hinter einer Secret-Referenz. `environ=None` heißt `os.environ`."""
    check_ref(ref)
    if ref.startswith("keyring:"):
        service, user = _split_keyring(ref)
        module = keyring_module if keyring_module is not None else _import_keyring()
        value = module.get_password(service, user)
        if not value:
            raise SecretMissing(
                _t("Kein Wert in den Windows-Anmeldeinformationen für {service}/{user} (tapesmith secret set …)", service=service, user=user))
        return value
    if ref.startswith("file:"):
        path = ref[len("file:"):]
        p = Path(path)
        if not p.exists():
            raise SecretMissing(_t("Datei {path} fehlt oder ist leer", path=path))
        text = p.read_text(encoding="utf-8")
        value = _first_value_from_file(text)
        if not value:
            raise SecretMissing(_t("Datei {path} fehlt oder ist leer", path=path))
        return value
    name = ref[len("env:"):]
    env = environ if environ is not None else os.environ
    value = env.get(name)
    if not value:
        raise SecretMissing(_t("Umgebungsvariable {name} fehlt oder ist leer", name=name))
    return value


def write_secret(ref: str, value: str, *, keyring_module=None) -> None:
    """Schreibt einen Wert. Nur für `keyring:`-Referenzen, sonst `ValueError`."""
    check_ref(ref)
    if not ref.startswith("keyring:"):
        raise ValueError(_t("Secret-Referenz {ref!r} lässt sich nicht schreiben (nur keyring:...)", ref=ref))
    if not value:
        raise ValueError(_t("Wert darf nicht leer sein"))
    service, user = _split_keyring(ref)
    module = keyring_module if keyring_module is not None else _import_keyring()
    module.set_password(service, user, value)


def has_secret(ref: str, **kw) -> bool:
    """True, wenn `read_secret` einen nicht leeren Wert liefert."""
    try:
        return bool(read_secret(ref, **kw))
    except SecretMissing:
        return False


def describe_ref(ref: str | None) -> str:
    """Menschlich lesbare Kurzbeschreibung des Orts, ohne den Wert selbst."""
    if not isinstance(ref, str):
        return _t("nicht gesetzt")
    if ref.startswith("keyring:"):
        return _t("Windows-Anmeldeinformationen {value}", value=ref[len('keyring:'):])
    if ref.startswith("file:"):
        return _t("Datei {value}", value=ref[len('file:'):])
    if ref.startswith("env:"):
        return _t("Umgebungsvariable {value}", value=ref[len('env:'):])
    return _t("nicht gesetzt")
