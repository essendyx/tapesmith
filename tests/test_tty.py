"""`is_interactive`: unter Windows meldet stdin aus `NUL` fälschlich `isatty() == True`."""

import io
import os

import pytest

from tapesmith import cli
from tapesmith.cli_cmds.base import is_interactive


def test_stringio_is_not_interactive():
    assert is_interactive(io.StringIO()) is False


class FakeTty(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_fake_tty_without_real_fileno_stays_interactive():
    # fileno() wirft io.UnsupportedOperation bei io.StringIO; bestehende CLI-Tests (test_cli_pipeline.py)
    # nutzen genau dieses Test-Double, um Rückfragen interaktiv zu beantworten.
    assert is_interactive(FakeTty()) is True


class NoIsatty:
    pass


class RaisingIsatty:
    def isatty(self) -> bool:
        raise ValueError("kaputt")


def test_missing_isatty_is_not_interactive():
    assert is_interactive(NoIsatty()) is False


def test_raising_isatty_is_not_interactive():
    assert is_interactive(RaisingIsatty()) is False


@pytest.mark.skipif(os.name != "nt", reason="NUL-Verhalten ist Windows-spezifisch")
def test_nul_reports_isatty_true_but_is_not_interactive():
    with open(os.devnull) as f:
        assert f.isatty() is True  # Vorbedingung: das ist genau die Windows-Falle
        assert is_interactive(f) is False


@pytest.mark.skipif(os.name != "nt", reason="NUL-Verhalten ist Windows-spezifisch")
def test_stdin_from_nul_does_not_block_confirmation(tmp_path, monkeypatch, capsys):
    devnull = open(os.devnull)
    monkeypatch.setattr("sys.stdin", devnull)
    try:
        target = tmp_path / "job.bin"
        exit_code = cli.main(["--transport", f"file:{target}", "text", "X", "--copies", "6"])
    finally:
        devnull.close()
    assert exit_code == 1
    assert "mit --yes bestätigen" in capsys.readouterr().err
    assert not target.exists()
