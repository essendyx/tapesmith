"""Tests für 'tapesmith raw' und 'tapesmith density' über die CLI (nie echte Hardware, MemoryTransport)."""

import io
import sys

import pytest

from tapesmith import cli
from tapesmith.cli_cmds import base as cmd_base
from tapesmith.tape.profiles import find_tape
from tapesmith.transport.base import MemoryTransport

HEADER = bytes.fromhex("1b401d763000")


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(cli, "SLEEP", lambda s: None)


def _use_memory_transport(monkeypatch, responses=None):
    transport = MemoryTransport(responses or {})
    monkeypatch.setattr(cli, "open_transport", lambda *a, **kw: transport)
    return transport


# 12
def test_raw_sends_and_decodes(monkeypatch, capsys):
    _use_memory_transport(monkeypatch, {bytes.fromhex("1f1108"): bytes.fromhex("1a044b")})
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    assert cli.main(["--transport", "file:x", "raw", "1f1108"]) == 0
    out = capsys.readouterr().out
    assert "1a044b" in out
    assert "Akku 75 %" in out


# 13
def test_raw_blocked_command_not_sent(monkeypatch, capsys):
    transport = _use_memory_transport(monkeypatch)
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    assert cli.main(["--transport", "file:x", "raw", "1b370701"]) == 1
    err = capsys.readouterr().err
    assert "gesperrt" in err
    assert transport.written == []
    assert not transport.opened


# 14
def test_raw_unsafe_needs_confirmation(monkeypatch, capsys):
    _use_memory_transport(monkeypatch)
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    assert cli.main(["--transport", "file:x", "raw", "aabb"]) == 1
    assert "--unsafe" in capsys.readouterr().err

    _use_memory_transport(monkeypatch)
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    assert cli.main(["--transport", "file:x", "raw", "aabb", "--unsafe"]) == 1

    monkeypatch.setattr(cmd_base.CliContext, "stdin_is_tty", lambda self: True)
    monkeypatch.setattr(sys, "stdin", io.StringIO("JA\n"))
    transport = _use_memory_transport(monkeypatch)
    assert cli.main(["--transport", "file:x", "raw", "aabb", "--unsafe"]) == 0
    assert transport.written == [bytes.fromhex("aabb")]


# 15
def test_raw_interactive_console(monkeypatch, capsys):
    _use_memory_transport(monkeypatch, {bytes.fromhex("1f1108"): bytes.fromhex("1a044b")})
    monkeypatch.setattr(sys, "stdin", io.StringIO("1f1108\nlisten 0\nquit\n"))
    assert cli.main(["--transport", "file:x", "raw", "-i"]) == 0
    out = capsys.readouterr().out
    assert out.count("1a044b") == 1


# 16
def test_density_preview_writes_png_and_notes(monkeypatch, capsys, tmp_path):
    transport = _use_memory_transport(monkeypatch)
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    preview = tmp_path / "x.png"
    assert cli.main(["--transport", "file:x", "density", "--yes", "--values", "3,8",
                     "--no-save", "--preview", str(preview)]) == 0
    err = capsys.readouterr().err
    assert "Print-Master" in err
    assert "dunkler" in err
    assert preview.exists()
    assert transport.written == []
    assert not transport.opened


def test_density_prints_two_candidates_with_prelude(monkeypatch):
    transport = _use_memory_transport(monkeypatch)
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    assert cli.main(["--transport", "file:x", "density", "--yes", "--values", "3,8", "--no-save"]) == 0
    written = b"".join(transport.written)
    assert written.count(bytes.fromhex("1b4e0403")) == 1
    assert written.count(bytes.fromhex("1b4e0408")) == 1
    idx_prelude = written.index(bytes.fromhex("1b4e0403"))
    idx_header = written.index(HEADER)
    assert idx_prelude < idx_header


def test_density_save_stores_chosen_field(monkeypatch):
    _use_memory_transport(monkeypatch)
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    assert cli.main(["--transport", "file:x", "density", "--yes", "--values", "3,8", "--save", "2"]) == 0
    tape = find_tape("schwarz-weiss")
    assert tape.density == 8
    assert tape.density_family == "m110"
