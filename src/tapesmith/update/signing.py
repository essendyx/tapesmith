"""Ed25519-Signatur der Update-Manifeste.

Vertrauenswürdige öffentliche Schlüssel liegen in `trusted_keys.json` neben diesem Modul
(`{"keys": [{"id": "…", "public_key": "<Base64 der 32 Rohbytes>"}]}`), anfangs leer: ohne
Schlüssel ist kein Update möglich (`update.no_trusted_key`). Den privaten Schlüssel erzeugt der
Controller mit `tools/release.py keygen`; er liegt nie im Repo."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from tapesmith.update.errors import UpdateError
from tapesmith.i18n import N_, _t

TRUSTED_KEYS_PATH = Path(__file__).with_name("trusted_keys.json")

NO_KEY_MESSAGE = (N_("Kein vertrauenswürdiger Signaturschlüssel in dieser Version: Updates sind erst möglich, wenn ein Schlüssel hinterlegt ist."))


def _raw_public(key: Ed25519PublicKey) -> bytes:
    return key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def key_id(key: Ed25519PublicKey) -> str:
    """Erste 16 Hex-Zeichen der SHA-256 des Rohschlüssels."""
    return hashlib.sha256(_raw_public(key)).hexdigest()[:16]


def public_entry(key: Ed25519PublicKey) -> dict:
    return {"id": key_id(key), "public_key": base64.b64encode(_raw_public(key)).decode("ascii")}


def load_trusted_keys(path: Path = TRUSTED_KEYS_PATH) -> list[tuple[str, Ed25519PublicKey]]:
    """Schlüssel aus `path`. Fehlt die Datei oder ist sie leer: leere Liste. Unlesbar: `update.no_trusted_key`."""
    path = Path(path)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        entries = data["keys"]
        result = []
        for entry in entries:
            raw = base64.b64decode(entry["public_key"], validate=True)
            result.append((str(entry["id"]), Ed25519PublicKey.from_public_bytes(raw)))
        return result
    except (OSError, ValueError, KeyError, TypeError, binascii.Error) as exc:
        raise UpdateError("update.no_trusted_key", _t("trusted_keys.json unlesbar: {exc}", exc=exc)) from exc


def verify(data: bytes, signature_b64: str | bytes, keys: list[tuple[str, Ed25519PublicKey]]) -> str:
    """Prüft die Base64-Signatur über `data` gegen `keys`; gibt die passende Schlüssel-ID zurück."""
    if not keys:
        raise UpdateError("update.no_trusted_key", _t(NO_KEY_MESSAGE))
    text = signature_b64.decode("ascii", "replace") if isinstance(signature_b64, bytes) else signature_b64
    try:
        signature = base64.b64decode(text.strip(), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise UpdateError("update.signature_invalid", _t("Signatur des Update-Manifests ist kein Base64")) from exc
    for kid, key in keys:
        try:
            key.verify(signature, data)
        except InvalidSignature:
            continue
        return kid
    raise UpdateError("update.signature_invalid",
                      _t("Signatur des Update-Manifests passt zu keinem vertrauenswürdigen Schlüssel"))


def sign(data: bytes, private_key: Ed25519PrivateKey) -> str:
    return base64.b64encode(private_key.sign(data)).decode("ascii")


def generate_keypair() -> tuple[bytes, dict]:
    """Neues Schlüsselpaar: privater Schlüssel als PEM (PKCS8, ohne Passwort) und Eintrag für trusted_keys.json."""
    private = Ed25519PrivateKey.generate()
    pem = private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption())
    return pem, public_entry(private.public_key())


def load_private_key(path: Path) -> Ed25519PrivateKey:
    key = serialization.load_pem_private_key(Path(path).read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError(_t("{path} enthält keinen Ed25519-Schlüssel", path=path))
    return key
