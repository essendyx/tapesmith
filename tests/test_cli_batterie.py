"""CLI-Befehl `tapesmith batterie` (list/typ/print/wartung). Kein echter HA-Aufruf,
kein echtes Token: `TRANSPORT` wird durch `httpx.MockTransport` ersetzt."""

from __future__ import annotations

import json

from homelab_fakes import load_json, mock_transport, token_file, write_homelab
from tapesmith import cli
from tapesmith.cli_cmds import base as cmd_base
from tapesmith.cli_cmds import batterie as batterie_cmd
from tapesmith.device.profile import load_profile
from tapesmith.ipc.backend import local_planner
from tapesmith.pipeline import PrintOutcome
from tapesmith.printer import PrintResult
import pytest

# Integrationen im Produkt ohne Standardadressen: Tests nutzen neutrale Testadressen.
pytestmark = pytest.mark.usefixtures("homelab_test_defaults")

P = load_profile()
BATTERIES = load_json("homeassistant/template-batteries.json")


def _setup(tmp_path, monkeypatch, *, todo_entity=None, batteries_status=200, todo_status=200,
          todo_calls=None):
    ref = token_file(tmp_path, "ha_token")
    write_homelab({"homeassistant": {"token_ref": ref, "todo_entity": todo_entity}})
    routes = {
        "POST /api/template": (batteries_status, json.dumps(BATTERIES)),
        "POST /api/services/todo/add_item": (todo_status, {}),
    }
    transport = mock_transport(routes, calls=todo_calls)
    monkeypatch.setattr(batterie_cmd, "TRANSPORT", transport)


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


def test_list_shows_devices(tmp_path, monkeypatch, capsys):
    _setup(tmp_path, monkeypatch)
    code = cli.main(["batterie", "list"])
    out = capsys.readouterr().out
    assert code == 0
    assert "Fensterkontakt Bad" in out
    assert "Bewegungsmelder Flur" in out


def test_typ_stores_local_mapping(tmp_path, monkeypatch, capsys):
    _setup(tmp_path, monkeypatch)
    code = cli.main(["batterie", "typ", "sensor.x", "CR2032"])
    out = capsys.readouterr().out
    assert code == 0
    assert "CR2032" in out
    from tapesmith.integrations.homeassistant import BatteryTypes

    assert BatteryTypes().get("sensor.x") == "CR2032"

    code = cli.main(["batterie", "typ", "sensor.x", "-"])
    assert code == 0
    assert BatteryTypes().get("sensor.x") is None


def test_print_preview_writes_file(tmp_path, monkeypatch, capsys):
    _setup(tmp_path, monkeypatch)
    preview = tmp_path / "b.png"
    code = cli.main(["batterie", "print", "sensor.flur_bewegung_battery", "--preview", str(preview)])
    err = capsys.readouterr().err
    assert code == 0
    assert preview.is_file()
    assert "nicht eingebbar" not in err


def test_print_with_datum_dry_run(tmp_path, monkeypatch, capsys):
    _setup(tmp_path, monkeypatch)
    code = cli.main(["batterie", "print", "sensor.flur_bewegung_battery",
                     "--datum", "01.10.2026", "--dry-run"])
    assert code == 0


def test_wartung_todo_only_after_real_print(tmp_path, monkeypatch, capsys):
    calls: list = []
    _setup(tmp_path, monkeypatch, todo_entity="todo.hausaufgaben", todo_calls=calls)

    preview = tmp_path / "w.png"
    code = cli.main(["batterie", "wartung", "USV-Akku", "--intervall", "36", "--todo",
                     "--preview", str(preview)])
    assert code == 0
    assert calls == []

    backend = FakeBackend()
    monkeypatch.setattr(cmd_base, "BACKEND_FACTORY", lambda ctx, history: backend)
    code = cli.main(["batterie", "wartung", "USV-Akku", "--intervall", "36", "--todo"])
    assert code == 0
    assert len(calls) == 1
    body = json.loads(calls[0].content)
    assert body["entity_id"] == "todo.hausaufgaben"


def test_wartung_preview_without_todo_flag_sends_nothing(tmp_path, monkeypatch, capsys):
    calls: list = []
    _setup(tmp_path, monkeypatch, todo_entity="todo.hausaufgaben", todo_calls=calls)
    preview = tmp_path / "w.png"
    code = cli.main(["batterie", "wartung", "USV-Akku", "--intervall", "36", "--preview", str(preview)])
    assert code == 0
    assert preview.is_file()
    assert calls == []


def test_wartung_nur_todo_without_todo_entity_fails(tmp_path, monkeypatch, capsys):
    _setup(tmp_path, monkeypatch, todo_entity=None)
    code = cli.main(["batterie", "wartung", "USV-Akku", "--intervall", "12", "--nur-todo"])
    err = capsys.readouterr().err
    assert code == 1
    assert "To-do-Liste nicht eingerichtet" in err
