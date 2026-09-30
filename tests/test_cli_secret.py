"""Tests für `tapesmith secret set|check` (über `tapesmith.cli.main`)."""

import io

from tapesmith import cli
from tapesmith.cli_cmds import secret


class _FakeKeyring:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service, user):
        return self.values.get((service, user))

    def set_password(self, service, user, value):
        self.values[(service, user)] = value


def test_secret_set_mqtt_stdin_speichert_ueber_keyring(app_home, monkeypatch, capsys):
    fake = _FakeKeyring()
    monkeypatch.setattr(secret, "KEYRING", fake)
    monkeypatch.setattr("sys.stdin", io.StringIO("pw\n"))

    assert cli.main(["secret", "set", "mqtt", "--stdin"]) == 0
    out = capsys.readouterr().out
    assert "Gespeichert" in out
    assert "pw" not in out
    assert fake.values[("tapesmith", "mqtt")] == "pw"


def test_secret_set_telegram_nur_datei_referenz(app_home, capsys):
    assert cli.main(["secret", "set", "telegram"]) == 1
    err = capsys.readouterr().err
    assert "den Wert dort pflegen" in err


def test_secret_check_mqtt(app_home, monkeypatch, capsys):
    fake = _FakeKeyring()
    monkeypatch.setattr(secret, "KEYRING", fake)

    assert cli.main(["secret", "check", "mqtt"]) == 1
    err = capsys.readouterr().err
    assert "fehlt" in err

    fake.values[("tapesmith", "mqtt")] = "geheim"
    assert cli.main(["secret", "check", "mqtt"]) == 0
    out = capsys.readouterr().out
    assert "vorhanden" in out
    assert "geheim" not in out
