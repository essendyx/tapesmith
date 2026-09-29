"""Secret-Referenzen und Fehlerklassen."""

import sys

import pytest

from homelab_fakes import FakeKeyring
from tapesmith.integrations import credentials, errors
from tapesmith.integrations.errors import (
    AuthFailed,
    IntegrationError,
    NotConfigured,
    NotReachable,
    TokenMissing,
    UpstreamError,
)


def test_file_with_comment_blank_and_assignment(tmp_path):
    path = tmp_path / ".token"
    path.write_text("# Kommentar\n\nTOKEN=\"abc\"\nweiter\n", encoding="utf-8")
    assert credentials.read_secret(f"file:{path}", what="Paperless") == "abc"


def test_file_with_bom_and_plain_value(tmp_path):
    path = tmp_path / ".token"
    path.write_bytes("\ufeff  xyz-1  \r\n".encode("utf-8"))
    assert credentials.read_secret(f"file:{path}", what="Paperless") == "xyz-1"


def test_file_with_single_quotes(tmp_path):
    path = tmp_path / ".token"
    path.write_text("'q1'\n", encoding="utf-8")
    assert credentials.read_secret(f"file:{path}", what="X") == "q1"


def test_file_expands_environment_variables(tmp_path, monkeypatch):
    (tmp_path / ".token").write_text("v", encoding="utf-8")
    monkeypatch.setenv("P12_TEST_DIR", str(tmp_path))
    assert credentials.read_secret("file:%P12_TEST_DIR%\\.token", what="X") == "v"


def test_missing_file_is_token_missing(tmp_path):
    path = tmp_path / ".p"
    with pytest.raises(TokenMissing) as info:
        credentials.read_secret(f"file:{path}", what="Paperless")
    exc = info.value
    assert str(exc) == f"Zugangsdaten: Token fehlt: Paperless (Datei {path})"
    assert exc.http_status == 424
    assert exc.exit_code == 1
    assert str(path) in exc.hint
    assert "eine Zeile" in exc.hint


def test_empty_file_is_token_missing(tmp_path):
    path = tmp_path / ".p"
    path.write_text("# nur Kommentar\n\n", encoding="utf-8")
    with pytest.raises(TokenMissing):
        credentials.read_secret(f"file:{path}", what="Paperless")


def test_env_from_given_environ():
    assert credentials.read_secret("env:HA_TOKEN", what="HA", environ={"HA_TOKEN": "t1"}) == "t1"
    with pytest.raises(TokenMissing) as info:
        credentials.read_secret("env:HA_TOKEN", what="HA", environ={"HA_TOKEN": "  "})
    assert info.value.hint == "Umgebungsvariable HA_TOKEN setzen"
    with pytest.raises(TokenMissing):
        credentials.read_secret("env:HA_TOKEN", what="HA", environ={})


def test_keyring_with_fake():
    fake = FakeKeyring({("tapesmith", "paperless"): "k"})
    assert credentials.read_secret("keyring:tapesmith/paperless", what="Paperless", keyring_module=fake) == "k"
    with pytest.raises(TokenMissing) as info:
        credentials.read_secret("keyring:tapesmith/proxmox", what="Proxmox", keyring_module=fake)
    assert "p12 homelab secret tapesmith/proxmox" in info.value.hint
    assert "Windows-Anmeldeinformationen tapesmith/proxmox" in str(info.value)


def test_keyring_package_missing(monkeypatch):
    monkeypatch.setitem(sys.modules, "keyring", None)
    with pytest.raises(TokenMissing) as info:
        credentials.read_secret("keyring:tapesmith/paperless", what="Paperless")
    assert "Paket keyring fehlt" in info.value.hint


def test_none_ref_is_token_missing():
    with pytest.raises(TokenMissing) as info:
        credentials.read_secret(None, what="Paperless")
    assert str(info.value) == "Zugangsdaten: Token fehlt: Paperless (nicht gesetzt)"
    assert info.value.hint == "In homelab.json eine token_ref eintragen"


def test_has_secret(tmp_path):
    path = tmp_path / "t"
    assert credentials.has_secret(f"file:{path}") is False
    path.write_text("x", encoding="utf-8")
    assert credentials.has_secret(f"file:{path}") is True
    assert credentials.has_secret(None) is False
    assert credentials.has_secret("keyring:a/b", keyring_module=FakeKeyring({("a", "b"): "v"})) is True


@pytest.mark.parametrize("ref", ["keyring:nur", "keyring:/x", "keyring: a/b", "file:", "file:  ",
                                 "env:1X", "env:", "http://x", ""])
def test_check_ref_rejects(ref):
    with pytest.raises(ValueError):
        credentials.check_ref(ref)


@pytest.mark.parametrize("ref", ["keyring:tapesmith/paperless", "file:C:\\x\\.p", "env:HA_TOKEN"])
def test_check_ref_accepts(ref):
    assert credentials.check_ref(ref) == ref


def test_describe_ref():
    assert credentials.describe_ref(None) == "nicht gesetzt"
    assert credentials.describe_ref("keyring:tapesmith/paperless") == "Windows-Anmeldeinformationen tapesmith/paperless"
    assert credentials.describe_ref("file:C:\\x\\.ha_token") == "Datei C:\\x\\.ha_token"
    assert credentials.describe_ref("env:X") == "Umgebungsvariable X"


def test_write_secret_only_keyring():
    with pytest.raises(ValueError, match="Nur keyring:-Referenzen"):
        credentials.write_secret("file:x", "v")
    fake = FakeKeyring()
    credentials.write_secret("keyring:tapesmith/paperless", "neu", keyring_module=fake)
    assert fake.entries == {("tapesmith", "paperless"): "neu"}


def test_write_secret_without_keyring_package(monkeypatch):
    monkeypatch.setitem(sys.modules, "keyring", None)
    with pytest.raises(ValueError, match="Paket keyring fehlt"):
        credentials.write_secret("keyring:tapesmith/paperless", "neu")


def test_token_missing_str_example():
    exc = TokenMissing("Paperless", "file:C:\\x\\.p")
    assert str(exc) == "Zugangsdaten: Token fehlt: Paperless (Datei C:\\x\\.p)"
    assert exc.service == "Zugangsdaten"


def test_error_classes_status_and_exit_codes():
    assert (TokenMissing.http_status, TokenMissing.exit_code) == (424, 1)
    assert (NotConfigured.http_status, NotConfigured.exit_code) == (424, 1)
    assert (NotReachable.http_status, NotReachable.exit_code) == (503, 5)
    assert (AuthFailed.http_status, AuthFailed.exit_code) == (502, 1)
    assert (UpstreamError.http_status, UpstreamError.exit_code) == (502, 1)
    exc = NotReachable("Paperless", "nicht erreichbar (x)", hint="Netz prüfen")
    assert str(exc) == "Paperless: nicht erreichbar (x)"
    assert exc.message == "nicht erreichbar (x)" and exc.hint == "Netz prüfen"
    assert isinstance(exc, IntegrationError) and isinstance(exc, RuntimeError)
    assert errors.exit_code(exc) == 5
    assert errors.exit_code(ValueError("x")) == 1
