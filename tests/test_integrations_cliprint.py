"""Druckhilfen für CLI-Befehle. Nie echter Druck: --dry-run, --preview
oder ein Fake-Backend über `cli_cmds.base.BACKEND_FACTORY`."""

import argparse

import pytest

from tapesmith import cli, numbering
from tapesmith.cli_cmds import base as cmd_base
from tapesmith.device.profile import load_profile
from tapesmith.integrations import cliprint
from tapesmith.integrations.errors import NotReachable, TokenMissing
from tapesmith.ipc.backend import local_planner
from tapesmith.pipeline import PrintOutcome
from tapesmith.printer import PrintResult
from tapesmith.sshscan import SshError
from tapesmith.templates.store import find_template

P = load_profile()

DISK_ROWS = [
    {"host": "pmx10", "slot": "SSD-1", "sn": "S5Y1NX0R123456"},
    {"host": "pmx10", "slot": "SSD-2", "sn": "S5Y1NX0R654321"},
]


class FakeBackend:
    kind = "daemon"
    fallback_reason = ""

    def __init__(self):
        self.requests = []

    def plan(self, request):
        return local_planner({}, P)(request)

    def execute(self, request, *, cancel=None, on_progress=None, on_warning=None, on_cut_pause=None,
                enqueue_on_offline=False):
        self.requests.append(request)
        return PrintOutcome("ok", self.plan(request), results=[PrintResult(80, [], 0.1, "ok", 80)],
                            history_id=1)

    def close(self):
        pass


@pytest.fixture
def fake_backend(monkeypatch):
    backend = FakeBackend()
    monkeypatch.setattr(cmd_base, "BACKEND_FACTORY", lambda ctx, history: backend)
    return backend


def _series(argv, template="datentraeger"):
    parser = argparse.ArgumentParser()
    cliprint.add_series_options(parser, template=template)
    args = parser.parse_args(argv)
    return args, cli.make_context(args)


def _print_only(argv):
    parser = argparse.ArgumentParser()
    cmd_base.add_print_options(parser)
    args = parser.parse_args(argv)
    return args, cli.make_context(args)


def test_add_series_options_defaults():
    args, _ctx = _series([])
    assert args.template == "datentraeger"
    assert args.dry_run is False and args.contact_sheet is None and args.preview is None
    args, _ctx = _series(["--template", "vm-lxc", "--dry-run"])
    assert args.template == "vm-lxc" and args.dry_run is True


def test_dry_run_prints_summary_without_counters(capsys):
    args, ctx = _series(["--dry-run"])
    code = cliprint.print_rows(ctx, args, args.template, DISK_ROWS)
    out = capsys.readouterr().out
    assert code == 0
    assert "2 Labels" in out
    assert not (numbering.numbering_dir(ctx.load_config()) / "counters.json").exists()


def test_contact_sheet_is_written(tmp_path, capsys):
    sheet = tmp_path / "k.png"
    args, ctx = _series(["--dry-run", "--contact-sheet", str(sheet)])
    assert cliprint.print_rows(ctx, args, args.template, DISK_ROWS) == 0
    assert sheet.is_file()


def test_preview_writes_file_without_printing(tmp_path, capsys):
    preview = tmp_path / "p.png"
    args, ctx = _series(["--preview", str(preview)])
    assert cliprint.print_rows(ctx, args, args.template, DISK_ROWS) == 0
    assert preview.is_file()


def test_unknown_template_is_6(capsys):
    args, ctx = _series(["--dry-run"])
    assert cliprint.print_rows(ctx, args, "gibt-es-nicht", DISK_ROWS) == 6
    assert "gibt-es-nicht" in capsys.readouterr().err


def test_no_printable_rows_is_1(capsys):
    args, ctx = _series([])
    code = cliprint.print_rows(ctx, args, "datentraeger", [{"host": "pmx10"}])
    err = capsys.readouterr().err
    assert code == 1
    assert "Zeile 1" in err and "Keine druckbaren Zeilen" in err


def test_print_one_with_print_options_only(tmp_path, capsys):
    preview = tmp_path / "p.png"
    args, ctx = _print_only(["--preview", str(preview)])
    assert not hasattr(args, "dry_run")
    code = cliprint.print_one(ctx, args, "datentraeger",
                              {"host": "pmx30", "slot": "SSD-1", "sn": "S5Y1NX0R123456"})
    assert code == 0
    assert preview.is_file()


def test_print_one_with_print_options_only_prints(fake_backend, capsys):
    args, ctx = _print_only([])
    code = cliprint.print_one(ctx, args, "datentraeger",
                              {"host": "pmx30", "slot": "SSD-1", "sn": "S5Y1NX0R123456"})
    assert code == 0
    assert len(fake_backend.requests) == 1
    assert fake_backend.requests[0].meta.source == "cli"


VM_ROW = {"typ": "VM", "vmid": "111", "name": "webapp1", "ip_kurz": ".39", "ip": "192.0.2.39",
          "node": "pmx10", "host": "pmx10", "link": "https://x"}


def test_print_rows_filters_extra_keys(capsys):
    args, ctx = _series(["--dry-run"], template="vm-lxc")
    code = cliprint.print_rows(ctx, args, "vm-lxc", [VM_ROW])
    captured = capsys.readouterr()
    assert code == 0
    assert "unbekannte Felder" not in captured.err
    assert "Hinweis" not in captured.err
    assert "1 Labels" in captured.out
    kept, skipped = cliprint.filter_inputs(find_template("vm-lxc"), VM_ROW)
    assert kept == {"typ": "VM", "vmid": "111", "name": "webapp1", "ip_kurz": ".39"}
    assert skipped == []


def test_print_rows_hints_computed_field(capsys):
    args, ctx = _series(["--dry-run"], template="garantie")
    row = {"geraet": "X", "kaufdatum": "31.01.2026", "dauer": "24", "ende": "01.01.2030"}
    code = cliprint.print_rows(ctx, args, "garantie", [row, dict(row)])
    err = capsys.readouterr().err
    assert code == 0
    hint = "Hinweis: Feld 'Garantie bis' wird von der Vorlage berechnet, übergebener Wert ignoriert"
    assert err.count(hint) == 1
    kept, skipped = cliprint.filter_inputs(find_template("garantie"), row)
    assert "ende" not in kept and skipped == ["ende"]


def test_on_printed_only_after_real_print(tmp_path, monkeypatch, capsys):
    calls = []

    def counter():
        calls.append(1)

    args, ctx = _series(["--preview", str(tmp_path / "p.png")])
    assert cliprint.print_rows(ctx, args, "datentraeger", DISK_ROWS, on_printed=counter) == 0
    assert calls == []

    args, ctx = _series(["--dry-run"])
    assert cliprint.print_rows(ctx, args, "datentraeger", DISK_ROWS, on_printed=counter) == 0
    assert calls == []

    args, ctx = _series([])
    assert cliprint.print_rows(ctx, args, "gibt-es-nicht", DISK_ROWS, on_printed=counter) == 6
    assert calls == []

    backend = FakeBackend()
    monkeypatch.setattr(cmd_base, "BACKEND_FACTORY", lambda c, history: backend)
    args, ctx = _series([])
    assert cliprint.print_rows(ctx, args, "datentraeger", DISK_ROWS, on_printed=counter) == 0
    assert calls == [1]
    assert len(backend.requests) == 1
    assert len(backend.requests[0].labels) == 2


def test_run_guarded_integration_error(capsys):
    _args, ctx = _series([])

    def fail():
        raise NotReachable("Paperless", "nicht erreichbar (http://x)", hint="Adresse und Netz prüfen")

    assert cliprint.run_guarded(ctx, fail) == 5
    lines = capsys.readouterr().err.strip().splitlines()
    assert lines == ["Paperless: nicht erreichbar (http://x)", "Hinweis: Adresse und Netz prüfen"]


def test_run_guarded_token_missing_is_1(capsys):
    _args, ctx = _series([])

    def fail():
        raise TokenMissing("Paperless", None)

    assert cliprint.run_guarded(ctx, fail) == 1
    assert "Token fehlt" in capsys.readouterr().err


def test_run_guarded_value_key_ssh_errors(capsys):
    _args, ctx = _series([])

    def value_error():
        raise ValueError("kaputt")

    def key_error():
        raise KeyError("Schlüssel fehlt")

    def ssh_error():
        raise SshError("SSH pmx10 nicht erreichbar")

    assert cliprint.run_guarded(ctx, value_error) == 1
    assert cliprint.run_guarded(ctx, key_error) == 1
    assert cliprint.run_guarded(ctx, ssh_error) == 5
    assert cliprint.run_guarded(ctx, lambda: 0) == 0
    err = capsys.readouterr().err
    assert "kaputt" in err and "Schlüssel fehlt" in err and "SSH pmx10" in err
