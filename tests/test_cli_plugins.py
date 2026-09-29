import argparse
import sys
import types

import pytest
from PIL import Image

from tapesmith import cli, paths
from tapesmith.cli_cmds import base as cmd_base
from tapesmith.cli_cmds.base import CliContext, add_print_options, discover_commands, positive_int
from tapesmith.device.profile import save_calibration
from tapesmith.fileutil import FileLockTimeout
from tapesmith.jobs import JobMeta
from tapesmith.render.compose import RenderResult
from tapesmith.templates.model import TemplateError
from tapesmith.transport.base import TransportError


def test_discover_commands_finds_nothing_in_an_empty_package(monkeypatch):
    """discover_commands liest das echte cli_cmds-Paket; hier wird das Auffinden isoliert getestet,
    unabhängig davon, wie viele reale Befehlsmodule (status, qr, history, …) inzwischen existieren."""
    monkeypatch.setattr(cmd_base.pkgutil, "iter_modules", lambda path: [])
    result = discover_commands()
    assert isinstance(result, dict)
    assert result == {}


def test_discover_commands_finds_real_plugin_modules():
    # Mehrere Befehle (status, setup, history, qr, print) legen eigene Plugins
    # unter cli_cmds/ ab.
    result = discover_commands()
    assert isinstance(result, dict)
    assert "print" in result
    for mod in result.values():
        assert all(hasattr(mod, attr) for attr in ("COMMAND", "HELP", "register", "run"))


def _make_fake_plugin(command="hallo", run=None):
    mod = types.ModuleType(f"fake_{command}")
    mod.COMMAND = command
    mod.HELP = "Testbefehl"

    def register(parser):
        parser.add_argument("--name", default="Welt")

    def default_run(args, ctx):
        ctx.out(f"Hallo {args.name}")
        return 0

    mod.register = register
    mod.run = run or default_run
    return mod


def test_plugin_command_is_registered_and_runs(monkeypatch, capsys):
    fake = _make_fake_plugin()
    monkeypatch.setattr(cli, "discover_commands", lambda: {"hallo": fake})
    assert cli.main(["hallo", "--name", "P12"]) == 0
    assert "Hallo P12" in capsys.readouterr().out


def test_plugin_template_error_is_exit_6(monkeypatch):
    def run(args, ctx):
        raise TemplateError("kaputt")

    fake = _make_fake_plugin(run=run)
    monkeypatch.setattr(cli, "discover_commands", lambda: {"hallo": fake})
    assert cli.main(["hallo"]) == 6


def test_plugin_transport_error_is_exit_5(monkeypatch):
    def run(args, ctx):
        raise TransportError("weg")

    fake = _make_fake_plugin(run=run)
    monkeypatch.setattr(cli, "discover_commands", lambda: {"hallo": fake})
    assert cli.main(["hallo"]) == 5


def test_plugin_file_lock_timeout_is_exit_7(monkeypatch):
    def run(args, ctx):
        raise FileLockTimeout("gesperrt")

    fake = _make_fake_plugin(run=run)
    monkeypatch.setattr(cli, "discover_commands", lambda: {"hallo": fake})
    assert cli.main(["hallo"]) == 7


def test_plugin_colliding_with_builtin_command_raises(monkeypatch):
    fake = _make_fake_plugin(command="text")
    monkeypatch.setattr(cli, "discover_commands", lambda: {"text": fake})
    with pytest.raises(RuntimeError):
        cli.main(["text"])


def test_add_print_options_rejects_zero_copies():
    parser = argparse.ArgumentParser()
    add_print_options(parser)
    with pytest.raises(SystemExit):
        parser.parse_args(["--copies", "0"])


def test_add_print_options_parses_chain_and_yes():
    parser = argparse.ArgumentParser()
    add_print_options(parser)
    args = parser.parse_args(["--copies", "3", "--chain", "--yes"])
    assert args.copies == 3
    assert args.chain is True
    assert args.yes is True


def test_positive_int_rejects_less_than_one():
    with pytest.raises(argparse.ArgumentTypeError):
        positive_int("0")
    assert positive_int("2") == 2


class FakeSession:
    class _Transport:
        supports_responses = False

    def __init__(self):
        self.printed = []
        self.transport = self._Transport()

    def print_image(self, head, cancel=None, on_progress=None):
        from tapesmith.printer import PrintResult
        self.printed.append(head)
        return PrintResult(head.height, [], 0.0)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_result(**overrides):
    defaults = dict(
        landscape=Image.new("1", (40, 20), 255),
        head=Image.new("1", (96, 40), 255),
        font_size=None,
        qr=None,
        warnings=[],
        length_mm=10.0,
        tape_mm=30.0,
        lead_rows=0,
        trail_rows=0,
        content_top=0,
    )
    defaults.update(overrides)
    return RenderResult(**defaults)


def _fake_ctx(args_ns, session):
    from tapesmith.device.profile import load_profile

    return CliContext(
        args=args_ns,
        load_config=lambda: {},
        load_profile=load_profile,
        open_session=lambda profile: session,
        emit_label=None,
        emit_head=None,
        stdin=sys.stdin,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )


def test_default_emit_label_prints_requested_copies(capsys):
    # über die Pipeline: Kopien = Einzeljobs, Bandbilanz statt "2 Kopien"
    session = FakeSession()
    args = argparse.Namespace(preview=None, copies=2, chain=False, export=None)
    ctx = _fake_ctx(args, session)
    assert cmd_base.default_emit_label(ctx, _fake_result(), JobMeta()) is True
    assert len(session.printed) == 2
    assert "Band: 2 Labels" in capsys.readouterr().out


def test_default_emit_label_preview_writes_png_without_printing(tmp_path, capsys):
    session = FakeSession()
    preview = tmp_path / "p.png"
    args = argparse.Namespace(preview=preview, copies=1, chain=False, export=None)
    ctx = _fake_ctx(args, session)
    assert cmd_base.default_emit_label(ctx, _fake_result(), JobMeta()) is False
    assert preview.exists()
    assert session.printed == []


def test_default_emit_label_chain_prints_one_job(capsys):
    # --chain ist verdrahtet (vorher ValueError "noch nicht verdrahtet")
    session = FakeSession()
    args = argparse.Namespace(preview=None, copies=3, chain=True, export=None)
    ctx = _fake_ctx(args, session)
    assert cmd_base.default_emit_label(ctx, _fake_result(), JobMeta()) is True
    assert len(session.printed) == 1
    assert session.printed[0].height > 3 * 40
    assert "statt" in capsys.readouterr().out


def test_make_context_loads_profile_with_calibration_and_caches_it(app_home):
    save_calibration(paths.calibration_path(), content_offset=6)
    ctx = cli.make_context(cli._parser({}).parse_args(["ports"]))
    profile = ctx.load_profile()
    assert profile.content_offset == 6
    assert ctx.load_profile() is profile


def test_make_context_uses_default_profile_without_calibration_file(app_home):
    ctx = cli.make_context(cli._parser({}).parse_args(["ports"]))
    assert ctx.load_profile().content_offset != 6


def test_plugin_emits_head_through_real_file_transport(tmp_path, monkeypatch):
    job = tmp_path / "job.bin"
    monkeypatch.setattr(cli, "SLEEP", lambda s: None)

    def register(parser):
        pass

    def run(args, ctx):
        head = Image.new("1", (96, 16), 255)
        ctx.emit_head(head, JobMeta())
        return 0

    fake = _make_fake_plugin()
    fake.register = register
    fake.run = run
    monkeypatch.setattr(cli, "discover_commands", lambda: {"hallo": fake})
    assert cli.main(["--transport", f"file:{job}", "hallo"]) == 0
    assert job.read_bytes().hex().startswith("1f1138")
