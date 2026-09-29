"""Ed25519-Signatur der Update-Manifeste (nur Testschlüssel, im Speicher bzw. tmp_path)."""

from __future__ import annotations

import base64
import json

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tapesmith.errors import error_code
from tapesmith.update import signing
from tapesmith.update.errors import UpdateError
from update_fakes import make_test_key

DATA = b'{"app": "tapesmith"}\n'


def test_sign_und_verify_liefert_schluessel_id():
    private, keys = make_test_key()
    sig = signing.sign(DATA, private)
    assert signing.verify(DATA, sig, keys) == keys[0][0]
    assert signing.verify(DATA, sig.encode() + b"\n", keys) == keys[0][0]


def test_ein_byte_geaendert_signature_invalid():
    private, keys = make_test_key()
    sig = signing.sign(DATA, private)
    changed = bytearray(DATA)
    changed[3] ^= 1
    with pytest.raises(UpdateError) as info:
        signing.verify(bytes(changed), sig, keys)
    assert info.value.code == "update.signature_invalid"
    assert error_code(info.value) == "update.signature_invalid"
    assert info.value.http_status == 502


def test_fremder_schluessel_und_kaputte_signatur():
    private, _keys = make_test_key()
    _other, other_keys = make_test_key()
    with pytest.raises(UpdateError, match="keinem"):
        signing.verify(DATA, signing.sign(DATA, private), other_keys)
    with pytest.raises(UpdateError) as info:
        signing.verify(DATA, "kein base64 !!", other_keys)
    assert info.value.code == "update.signature_invalid"


def test_leere_schluesselliste_no_trusted_key():
    private, _keys = make_test_key()
    with pytest.raises(UpdateError) as info:
        signing.verify(DATA, signing.sign(DATA, private), [])
    assert info.value.code == "update.no_trusted_key"
    assert info.value.http_status == 409
    assert "Kein vertrauenswürdiger Signaturschlüssel" in str(info.value)


def test_mitgeliefertes_trusted_keys_json_ist_gueltig():
    data = json.loads(signing.TRUSTED_KEYS_PATH.read_text(encoding="utf-8"))
    assert set(data) == {"keys"}
    loaded = signing.load_trusted_keys()
    assert len(loaded) == len(data["keys"])
    for entry, (kid, key) in zip(data["keys"], loaded):
        assert len(base64.b64decode(entry["public_key"])) == 32
        assert kid == entry["id"] == signing.key_id(key)


def test_generate_keypair_und_laden(tmp_path):
    pem, entry = signing.generate_keypair()
    assert pem.startswith(b"-----BEGIN PRIVATE KEY-----")
    assert len(entry["id"]) == 16
    assert len(base64.b64decode(entry["public_key"])) == 32
    key_file = tmp_path / "priv.pem"
    key_file.write_bytes(pem)
    private = signing.load_private_key(key_file)
    trusted = tmp_path / "trusted_keys.json"
    trusted.write_text(json.dumps({"keys": [entry]}), encoding="utf-8")
    keys = signing.load_trusted_keys(trusted)
    assert signing.verify(DATA, signing.sign(DATA, private), keys) == entry["id"]


def test_load_trusted_keys_fehlt_bzw_kaputt(tmp_path):
    assert signing.load_trusted_keys(tmp_path / "gibtsnicht.json") == []
    bad = tmp_path / "bad.json"
    bad.write_text('{"keys": [{"id": "x", "public_key": "!!"}]}', encoding="utf-8")
    with pytest.raises(UpdateError) as info:
        signing.load_trusted_keys(bad)
    assert info.value.code == "update.no_trusted_key"


def test_load_private_key_falscher_typ(tmp_path):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    key = ec.generate_private_key(ec.SECP256R1())
    path = tmp_path / "ec.pem"
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption()))
    with pytest.raises(ValueError, match="Ed25519"):
        signing.load_private_key(path)
    assert isinstance(Ed25519PrivateKey.generate(), Ed25519PrivateKey)


def test_update_error_nur_vertragscodes():
    with pytest.raises(ValueError):
        UpdateError("update.gibtsnicht", "x")
    err = UpdateError("update.busy", "belegt", hint="später")
    assert (err.code, err.http_status, err.hint) == ("update.busy", 409, "später")
