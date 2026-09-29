"""CLI druckt über das Druck-Backend (Dienst oder direkt), exklusive Befehle unter Lease."""

import contextlib
import json
from datetime import datetime
from pathlib import Path

import pytest

from tapesmith import cli, paths
from tapesmith.cli_cmds import base as cmd_base
from tapesmith.device.profile import load_profile
from tapesmith.ipc.backend import LocalBackend, local_planner
from tapesmith.ipc.codec import StateInfo, StatusReport
from tapesmith.pipeline import PrintOutcome
from tapesmith.printer import PrintResult
from tapesmith.status import status_from_bytes
from tapesmith.templates.store import user_dir
from tapesmith.transport.base import MemoryTransport

GOLDEN = Path(__file__).parent / "golden"
P = load_profile()
NOW = datetime(2026, 9, 27, 12, 0, 0)


class FakeBackend:
    kind = "daemon"

    def __init__(self, status="ok", queue_id=None, warnings=("Akku niedrig (15 %)",), fallback_reason=""):
        self.status = status
        self.queue_id = queue_id
        self.warnings = warnings
        self.fallback_reason = fallback_reason
        self.requests = []
        self.enqueue = []
        self.leases = 0
        self.releases = 0
        self.status_calls = []
        self.closed = False
        self.events = []

    def plan(self, request):
        return local_planner({}, P)(request)

    def execute(self, request, *, cancel=None, on_progress=None, on_warning=None, on_cut_pause=None,
                enqueue_on_offline=False):
        self.requests.append(request)
        self.enqueue.append(enqueue_on_offline)
        for text in self.warnings:
            on_warning(text)
        results = [] if self.status == "wartet" else [PrintResult(80, [], 0.1, "ok", 80)]
        return PrintOutcome(self.status, self.plan(request), results=results,
                            history_id=None if self.status == "wartet" else 7, queue_id=self.queue_id)

    @contextlib.contextmanager
    def lease(self, timeout_s=120.0):
        self.leases += 1
        self.events.append("lease")
        try:
            yield
        finally:
            self.releases += 1
            self.events.append("release")

    def query_status(self, *, quick=False, fresh=True):
        self.status_calls.append({"quick": quick, "fresh": fresh})
        return StatusReport(StateInfo("verbunden", "COM4"), status_from_bytes(bytes.fromhex("1a044b1a0598"), P),
                            NOW)

    def close(self):
        self.closed = True


@pytest.fixture
def fake(monkeypatch):
    backend = FakeBackend()
    monkeypatch.setattr(cmd_base, "BACKEND_FACTORY", lambda ctx, history: backend)
    return backend


def write_config(data: dict) -> None:
    path = paths.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


# 17 ----------------------------------------------------------------------------------------

def test_default_in_tests_is_direct_and_golden(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "SLEEP", lambda s: None)
    out = tmp_path / "job.bin"
    assert cli.main(["--transport", f"file:{out}", "print-image", str(GOLDEN / "ref_label.pbm")]) == 0
    assert out.read_bytes() == (GOLDEN / "ref_stream.bin").read_bytes()
    text_job = tmp_path / "text.bin"
    assert cli.main(["--transport", f"file:{text_job}", "text", "x"]) == 0
    assert text_job.stat().st_size > 0
    assert "gedruckt" in capsys.readouterr().out


# 18 ----------------------------------------------------------------------------------------

def test_print_goes_through_backend(fake, capsys):
    assert cli.main(["text", "Hallo"]) == 0
    captured = capsys.readouterr()
    assert len(fake.requests) == 1
    assert fake.requests[0].meta.source == "cli"
    assert fake.requests[0].meta.title == "Hallo"
    assert "Warnung: Akku niedrig (15 %)" in captured.err
    assert "gedruckt" in captured.out
    assert "(Verlauf #7)" in captured.out
    assert fake.closed


def test_fallback_reason_is_printed(monkeypatch, capsys):
    backend = FakeBackend(fallback_reason="Druckdienst nicht erreichbar, drucke direkt", warnings=())
    monkeypatch.setattr(cmd_base, "BACKEND_FACTORY", lambda ctx, history: backend)
    assert cli.main(["text", "Hallo"]) == 0
    assert "Hinweis: Druckdienst nicht erreichbar, drucke direkt" in capsys.readouterr().err


# 19 ----------------------------------------------------------------------------------------

def test_waiting_with_queue_flag(monkeypatch, capsys):
    backend = FakeBackend(status="wartet", queue_id=4, warnings=())
    monkeypatch.setattr(cmd_base, "BACKEND_FACTORY", lambda ctx, history: backend)
    assert cli.main(["text", "Hallo", "--queue"]) == 0
    out = capsys.readouterr().out
    assert "#4" in out and "Warteschlange" in out and "p12 queue list" in out
    assert backend.enqueue == [True]


def test_without_queue_flag_enqueue_is_false_unless_configured(fake, capsys):
    assert cli.main(["text", "Hallo"]) == 0
    assert fake.enqueue == [False]
    write_config({"queue": {"cli_default": True}})
    assert cli.main(["text", "Hallo"]) == 0
    assert fake.enqueue == [False, True]


def test_preview_never_uses_backend(fake, tmp_path, capsys):
    out = tmp_path / "v.png"
    assert cli.main(["text", "Hallo", "--preview", str(out)]) == 0
    assert out.is_file()
    assert fake.requests == []


# 20 ----------------------------------------------------------------------------------------

def _forbid_daemon(monkeypatch):
    monkeypatch.delenv("TAPESMITH_NO_DAEMON", raising=False)

    def forbidden(*a, **kw):
        pytest.fail("Druckdienst darf hier nicht benutzt werden")

    monkeypatch.setattr(cmd_base, "make_backend", forbidden)


def test_no_daemon_and_file_transport_force_local(monkeypatch, tmp_path, capsys):
    _forbid_daemon(monkeypatch)
    monkeypatch.setattr(cli, "SLEEP", lambda s: None)
    built = []
    real = cmd_base.build_backend

    def spy(ctx, history):
        backend = real(ctx, history)
        built.append(backend)
        return backend

    monkeypatch.setattr(cmd_base, "build_backend", spy)
    job = tmp_path / "job.bin"
    assert cli.main(["--transport", f"file:{job}", "text", "x"]) == 0
    assert job.exists()

    memory = MemoryTransport()
    monkeypatch.setattr(cli, "open_transport", lambda spec, mac, hexlog=None, **kw: memory)
    assert cli.main(["--no-daemon", "text", "x"]) == 0
    assert memory.written
    assert all(isinstance(b, LocalBackend) for b in built) and len(built) == 2


def test_without_flags_uses_make_backend(monkeypatch, capsys):
    monkeypatch.delenv("TAPESMITH_NO_DAEMON", raising=False)
    backend = FakeBackend(warnings=())
    seen = {}

    def fake_make_backend(cfg, profile, *, client, local_factory, planner=None, **kw):
        seen["client"] = client
        seen["planner"] = planner
        return backend

    monkeypatch.setattr(cmd_base, "make_backend", fake_make_backend)
    assert cli.main(["text", "Hallo"]) == 0
    assert seen["client"] == "cli" and seen["planner"] is not None
    assert len(backend.requests) == 1


# 21 ----------------------------------------------------------------------------------------

def test_preview_is_never_blocked_by_tape_question(tmp_path, capsys, monkeypatch):
    write_config({"tape": {"current": "schwarz-weiss-papier"}})
    out = tmp_path / "v.png"
    assert cli.main(["template", "print", "gefriergut", "--set", "inhalt=Suppe", "--preview", str(out)]) == 0
    assert out.is_file()
    assert "Rückfrage" not in capsys.readouterr().err

    monkeypatch.setattr(cli, "SLEEP", lambda s: None)
    job = tmp_path / "job.bin"
    assert cli.main(["--transport", f"file:{job}", "template", "print", "gefriergut", "--set", "inhalt=Suppe"]) == 1
    assert "mit --yes bestätigen" in capsys.readouterr().err


# 22 ----------------------------------------------------------------------------------------

class FakeSession:
    def __init__(self, events):
        self.events = events

    def __enter__(self):
        self.events.append("session")
        return self

    def __exit__(self, *exc):
        return False

    def query(self, cmd):
        self.events.append(f"query {cmd}")
        return bytes.fromhex("1a044b")


def test_exclusive_command_runs_under_lease(monkeypatch, capsys):
    monkeypatch.delenv("TAPESMITH_NO_DAEMON", raising=False)
    backend = FakeBackend()
    monkeypatch.setattr(cmd_base, "BACKEND_FACTORY", lambda ctx, history: backend)
    monkeypatch.setattr(cli, "daemon_running", lambda **kw: True)
    monkeypatch.setattr(cli, "_session", lambda args, cfg, profile: FakeSession(backend.events))

    assert cli.main(["probe", "1f1108"]) == 0
    captured = capsys.readouterr()
    assert "1a044b" in captured.out
    assert "gibt den Drucker für diesen Befehl frei" in captured.err
    assert (backend.leases, backend.releases) == (1, 1)
    assert backend.events == ["lease", "session", "query 1f1108", "release"]

    # auch mit ausdrücklichem COM-Port (der Dienst hält denselben Drucker)
    assert cli.main(["--transport", "COM9", "probe", "1f1108"]) == 0
    assert backend.leases == 2


def test_exclusive_command_without_daemon_or_with_no_daemon(monkeypatch, capsys):
    monkeypatch.delenv("TAPESMITH_NO_DAEMON", raising=False)
    backend = FakeBackend()
    monkeypatch.setattr(cmd_base, "BACKEND_FACTORY", lambda ctx, history: backend)
    monkeypatch.setattr(cli, "_session", lambda args, cfg, profile: FakeSession(backend.events))

    monkeypatch.setattr(cli, "daemon_running", lambda **kw: False)
    assert cli.main(["probe", "1f1108"]) == 0
    assert backend.leases == 0

    monkeypatch.setattr(cli, "daemon_running", lambda **kw: True)
    assert cli.main(["--no-daemon", "probe", "1f1108"]) == 0
    assert backend.leases == 0
    assert cli.main(["--transport", "file:x.bin", "probe", "1f1108"]) == 0
    assert backend.leases == 0
    assert "gibt den Drucker" not in capsys.readouterr().err


def test_lease_busy_is_exit_7(monkeypatch, capsys):
    from tapesmith.lock import PrinterBusy

    monkeypatch.delenv("TAPESMITH_NO_DAEMON", raising=False)

    class BusyBackend(FakeBackend):
        @contextlib.contextmanager
        def lease(self, timeout_s=120.0):
            raise PrinterBusy("Druckauftrag läuft")
            yield

    monkeypatch.setattr(cmd_base, "BACKEND_FACTORY", lambda ctx, history: BusyBackend())
    monkeypatch.setattr(cli, "daemon_running", lambda **kw: True)
    monkeypatch.setattr(cli, "_session", lambda *a: pytest.fail("darf nicht laufen"))
    assert cli.main(["probe", "1f1108"]) == 7


def test_remote_error_uses_its_exit_code(monkeypatch, capsys):
    from tapesmith.ipc.codec import RemoteError

    class Broken(FakeBackend):
        def execute(self, request, **kw):
            raise RemoteError("Unbekannt", "Dienst kaputt", 1)

    monkeypatch.setattr(cmd_base, "BACKEND_FACTORY", lambda ctx, history: Broken())
    assert cli.main(["text", "x"]) == 1
    assert "Fehler: Dienst kaputt" in capsys.readouterr().err


def test_daemon_lost_is_exit_5(monkeypatch, capsys):
    from tapesmith.ipc.client import DaemonLost

    class Lost(FakeBackend):
        def execute(self, request, **kw):
            raise DaemonLost()

    monkeypatch.setattr(cmd_base, "BACKEND_FACTORY", lambda ctx, history: Lost())
    assert cli.main(["text", "x"]) == 5
    assert "Verlauf" in capsys.readouterr().err


# 23 ----------------------------------------------------------------------------------------

def test_status_cached_through_backend(fake, capsys):
    assert cli.main(["status", "--cached"]) == 0
    assert fake.status_calls == [{"quick": False, "fresh": False}]
    out = capsys.readouterr().out
    assert "Akku" in out and "Deckel" in out


def test_status_json_contains_state(fake, capsys):
    assert cli.main(["status", "--json", "--quick"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["state"]["state"] == "verbunden"
    assert data["values"]["battery"]["value"] == 75
    assert fake.status_calls == [{"quick": True, "fresh": True}]


# 24 ----------------------------------------------------------------------------------------

def _counter_template(tmp_path):
    tpl = tmp_path / "zaehler.tapesmith.json"
    tpl.write_text(json.dumps({
        "schema_version": 1, "name": "zaehler", "description": "",
        "fields": [{"id": "nr", "label": "Nr", "type": "counter", "format": "ASN{:05d}"}],
        "layout": {"lines": ["{nr}"]},
    }), encoding="utf-8")
    return tpl


def test_template_counters_use_central_numbering_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "SLEEP", lambda s: None)
    central = tmp_path / "zentral"
    write_config({"numbering": {"dir": str(central)}})
    tpl = _counter_template(tmp_path)
    job = tmp_path / "j.bin"
    assert cli.main(["--transport", f"file:{job}", "template", "print", str(tpl)]) == 0
    assert json.loads((central / "counters.json").read_text(encoding="utf-8")) == {"zaehler.nr": 1}
    assert not (paths.app_dir() / "counters.json").exists()


def test_batch_counters_use_central_numbering_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "SLEEP", lambda s: None)
    central = tmp_path / "zentral"
    write_config({"numbering": {"dir": str(central)}})
    tpl = _counter_template(tmp_path)
    user_dir().mkdir(parents=True, exist_ok=True)
    (user_dir() / "zaehler.tapesmith.json").write_text(tpl.read_text(encoding="utf-8"), encoding="utf-8")
    lines = tmp_path / "zeilen.txt"
    lines.write_text("a\nb\n", encoding="utf-8")
    job = tmp_path / "j.bin"
    assert cli.main(["--transport", f"file:{job}", "batch", "zaehler", "--lines", str(lines), "--yes"]) == 0
    assert json.loads((central / "counters.json").read_text(encoding="utf-8")) == {"zaehler.nr": 2}


# doctor: USB- und Dienst-Zeile ------------------------------------------------------------

def test_doctor_reports_daemon(monkeypatch, capsys):
    from tapesmith.transport import btports

    monkeypatch.setattr(btports, "_read_registry", lambda: [])
    monkeypatch.setattr(cli, "usb_check", lambda: cli.Check("USB (experimentell)", True, "kein Gerät"))
    monkeypatch.delenv("TAPESMITH_NO_DAEMON", raising=False)
    monkeypatch.setattr(cli, "daemon_pid", lambda **kw: 4242)
    cli.main(["doctor", "--no-connect", "--json"])
    checks = {c["name"]: c for c in json.loads(capsys.readouterr().out)}
    assert checks["Druckdienst"]["detail"] == "läuft (PID 4242)" and checks["Druckdienst"]["ok"]
    assert "USB (experimentell)" in checks

    monkeypatch.setattr(cli, "daemon_pid", lambda **kw: None)
    cli.main(["doctor", "--no-connect", "--json"])
    checks = {c["name"]: c for c in json.loads(capsys.readouterr().out)}
    assert checks["Druckdienst"]["detail"] == "läuft nicht, startet bei Bedarf" and checks["Druckdienst"]["ok"]
