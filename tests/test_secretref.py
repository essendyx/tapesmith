"""Tests für `tapesmith.secretref`."""

import sys

import pytest

from tapesmith import secretref
from tapesmith.secretref import SecretMissing, check_ref, describe_ref, read_secret, write_secret


class FakeKeyring:
    def __init__(self):
        self._store: dict[tuple[str, str], str] = {}

    def get_password(self, service, user):
        return self._store.get((service, user))

    def set_password(self, service, user, value):
        self._store[(service, user)] = value


# ---------- check_ref ----------

@pytest.mark.parametrize("value", [
    "keyring:tapesmith/mqtt",
    "file:C:/tmp/token.txt",
    "env:TELEGRAM_BOT_TOKEN",
])
def test_check_ref_akzeptiert_gueltige_formen(value):
    assert check_ref(value) == value


@pytest.mark.parametrize("value", ["keyring:nur", "file:", "env:1X", "klartext", ""])
def test_check_ref_lehnt_ungueltige_formen_ab(value):
    with pytest.raises(ValueError):
        check_ref(value)


def test_check_ref_lehnt_leerzeichen_am_rand_ab():
    with pytest.raises(ValueError):
        check_ref("keyring: tapesmith/mqtt")
    with pytest.raises(ValueError):
        check_ref("keyring:tapesmith/mqtt ")


# ---------- read_secret: file: ----------

@pytest.mark.parametrize("content,expected", [
    ("abc\n", "abc"),
    ("# kommentar\n\nabc", "abc"),
    ("TELEGRAM_BOT_TOKEN=abc", "abc"),
    ('BOT="abc"', "abc"),
])
def test_read_secret_datei_formen(tmp_path, content, expected):
    path = tmp_path / "token.txt"
    path.write_text(content, encoding="utf-8")
    assert read_secret(f"file:{path}") == expected


def test_read_secret_datei_fehlt():
    with pytest.raises(SecretMissing):
        read_secret("file:C:/does/not/exist.txt")


def test_read_secret_datei_leer(tmp_path):
    path = tmp_path / "leer.txt"
    path.write_text("", encoding="utf-8")
    with pytest.raises(SecretMissing):
        read_secret(f"file:{path}")


def test_secretmissing_meldung_enthaelt_nie_den_wert(tmp_path):
    path = tmp_path / "geheim.txt"
    path.write_text("GEHEIMWERT", encoding="utf-8")
    assert read_secret(f"file:{path}") == "GEHEIMWERT"

    fake = FakeKeyring()
    with pytest.raises(SecretMissing) as exc_info:
        read_secret("keyring:tapesmith/mqtt", keyring_module=fake)
    assert "GEHEIMWERT" not in str(exc_info.value)


# ---------- read_secret / write_secret: keyring: ----------

def test_write_and_read_secret_keyring():
    fake = FakeKeyring()
    write_secret("keyring:tapesmith/mqtt", "pw", keyring_module=fake)
    assert read_secret("keyring:tapesmith/mqtt", keyring_module=fake) == "pw"


def test_write_secret_nur_keyring():
    with pytest.raises(ValueError):
        write_secret("file:x", "pw")


def test_write_secret_leerer_wert():
    fake = FakeKeyring()
    with pytest.raises(ValueError):
        write_secret("keyring:tapesmith/mqtt", "", keyring_module=fake)


def test_read_secret_keyring_ohne_eintrag():
    fake = FakeKeyring()
    with pytest.raises(SecretMissing):
        read_secret("keyring:tapesmith/mqtt", keyring_module=fake)


def test_read_secret_keyring_paket_fehlt(monkeypatch):
    monkeypatch.setitem(sys.modules, "keyring", None)
    with pytest.raises(SecretMissing, match="keyring"):
        read_secret("keyring:tapesmith/mqtt")


# ---------- read_secret: env: ----------

def test_read_secret_env():
    assert read_secret("env:X", environ={"X": "v"}) == "v"


def test_read_secret_env_fehlt():
    with pytest.raises(SecretMissing):
        read_secret("env:X", environ={})


# ---------- describe_ref ----------

def test_describe_ref():
    assert describe_ref(None) == "nicht gesetzt"
    assert "Windows-Anmeldeinformationen a/b" in describe_ref("keyring:a/b")
    assert "Datei" in describe_ref("file:C:/x")
    assert "Umgebungsvariable" in describe_ref("env:X")


# ---------- has_secret / is_ref ----------

def test_is_ref():
    assert secretref.is_ref("keyring:a/b")
    assert secretref.is_ref("file:x")
    assert secretref.is_ref("env:X")
    assert not secretref.is_ref("klartext")
    assert not secretref.is_ref(None)


def test_has_secret():
    fake = FakeKeyring()
    assert not secretref.has_secret("keyring:tapesmith/mqtt", keyring_module=fake)
    write_secret("keyring:tapesmith/mqtt", "pw", keyring_module=fake)
    assert secretref.has_secret("keyring:tapesmith/mqtt", keyring_module=fake)
