"""CLI-Befehl `tapesmith vault` (list, show, print, table, snippet). Nie echter Druck, nie echtes MCP."""

import json

import pytest
from PIL import Image, ImageDraw

from homelab_fakes import connect_error_transport, write_homelab
from obsidian_fakes import FakeMcp, vault_tools
from tapesmith import cli, paths
from tapesmith.cli_cmds import base as cmd_base
from tapesmith.cli_cmds import vault as vault_cmd
from tapesmith.device.profile import load_profile
from tapesmith.history import HistoryStore
from tapesmith.ipc.backend import local_planner
from tapesmith.jobs import JobMeta
from tapesmith.pipeline import PrintOutcome
from tapesmith.printer import PrintResult

# Integrationen im Produkt ohne Standardadressen: Tests nutzen neutrale Testadressen.
pytestmark = pytest.mark.usefixtures("homelab_test_defaults")

P = load_profile()


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
def fake(monkeypatch):
    mcp = FakeMcp(vault_tools())
    monkeypatch.setattr(vault_cmd, "TRANSPORT", mcp.transport())
    return mcp


@pytest.fixture
def backend(monkeypatch):
    printer = FakeBackend()
    monkeypatch.setattr(cmd_base, "BACKEND_FACTORY", lambda ctx, history: printer)
    return printer


def _appends(mcp):
    return [args for name, args in mcp.tool_calls if name == "vault_append"]


def test_help_builds_parser(capsys):
    with pytest.raises(SystemExit) as info:
        cli.main(["vault", "--help"])
    assert info.value.code == 0
    out = capsys.readouterr().out
    for sub in ("list", "show", "print", "table", "snippet"):
        assert sub in out
    with pytest.raises(SystemExit) as info:
        cli.main(["vault", "table", "--help"])
    assert info.value.code == 0


def test_list(fake, capsys):
    assert cli.main(["vault", "list"]) == 0
    assert capsys.readouterr().out.split() == ["Hosts/pmx30", "Dienste/testdienst"]
    assert cli.main(["vault", "list", "Privat"]) == 1
    assert "außerhalb der freigegebenen Ordner" in capsys.readouterr().err


def test_show(fake, capsys):
    assert cli.main(["vault", "show", "Hosts/pmx30"]) == 0
    out = capsys.readouterr().out
    assert "ip" in out and "192.0.2.99" in out
    assert "Tabelle 1 (Platten): Label | Seriennummer | Rolle [2 Zeilen]" in out
    assert "Tabelle 2 (Gäste)" in out
    assert cli.main(["vault", "show", "Hosts/pmx30", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["values"]["host"] == "pmx30"
    assert data["tables"][0]["rows"][0] == ["SSD-1", "111111274913", "rpool Spiegel"]


def test_print_preview_without_append(fake, tmp_path, capsys):
    write_homelab({"obsidian": {"append_after_print": True}})
    preview = tmp_path / "p.png"
    assert cli.main(["vault", "print", "Hosts/pmx30", "--template", "host-ip", "--preview", str(preview)]) == 0
    err = capsys.readouterr().err
    assert preview.is_file()
    assert "unbekannte Felder" not in err
    assert _appends(fake) == []
    assert cli.main(["vault", "print", "Hosts/pmx30", "--template", "host-ip", "--vermerk",
                     "--preview", str(tmp_path / "q.png")]) == 0
    assert _appends(fake) == []


def test_print_template_required_and_no_dry_run(fake, capsys):
    with pytest.raises(SystemExit) as info:
        cli.main(["vault", "print", "Hosts/pmx30"])
    assert info.value.code == 2
    with pytest.raises(SystemExit):
        cli.main(["vault", "print", "Hosts/pmx30", "--template", "host-ip", "--dry-run"])


def test_vault_print_appends_after_real_print(fake, backend, capsys):
    write_homelab({"obsidian": {"append_after_print": True}})
    assert cli.main(["vault", "print", "Hosts/pmx30", "--template", "host-ip"]) == 0
    out = capsys.readouterr().out
    assert len(backend.requests) == 1
    appends = _appends(fake)
    assert len(appends) == 1
    assert appends[0]["path"] == "Hosts/pmx30"
    assert appends[0]["content"].endswith("Label gedruckt: pmx30 · 192.0.2.99")
    assert "Vermerk angehängt: - " in out

    assert cli.main(["vault", "print", "Hosts/pmx30", "--template", "host-ip", "--kein-vermerk"]) == 0
    assert len(_appends(fake)) == 1

    write_homelab({"obsidian": {"append_after_print": False}})
    assert cli.main(["vault", "print", "Hosts/pmx30", "--template", "host-ip", "--vermerk"]) == 0
    assert len(_appends(fake)) == 2
    assert cli.main(["vault", "print", "Hosts/pmx30", "--template", "host-ip"]) == 0
    assert len(_appends(fake)) == 2
    assert len(backend.requests) == 4


def test_print_set_maps_fields(fake, backend, capsys):
    assert cli.main(["vault", "print", "Dienste/testdienst", "--template", "host-ip",
                     "--set", "rolle=port", "--kein-vermerk"]) == 0
    request = backend.requests[0]
    assert request.meta.values["rolle"] == "8080"
    assert request.meta.values["host"] == "docker99"
    assert cli.main(["vault", "print", "Dienste/testdienst", "--template", "host-ip",
                     "--set", "rolle=gibtsnicht"]) == 1
    assert "keinen Wert 'gibtsnicht'" in capsys.readouterr().err


def test_table_dry_run(fake, capsys):
    argv = ["vault", "table", "Hosts/pmx30", "1", "--spalte", "Seriennummer=sn", "--spalte", "Label=slot",
            "--dry-run"]
    assert cli.main(argv) == 0
    assert "2 Labels" in capsys.readouterr().out
    assert cli.main(argv + ["--template", "datentraeger"]) == 0
    assert cli.main(["vault", "table", "Hosts/pmx30", "3", "--dry-run"]) == 1
    assert "keine Tabelle 3" in capsys.readouterr().err


def test_table_rows_with_host(fake):
    from tapesmith.integrations.obsidian import note_values
    from obsidian_fakes import data_text
    from tapesmith.integrations.frontmatter import tables
    from tapesmith.integrations.obsidian import Note

    text = data_text("pmx30.md")
    note = Note("Hosts/pmx30", "pmx30", text, note_values("Hosts/pmx30", text), tuple(tables(text)))
    rows = vault_cmd._table_rows(note, 1, ["Seriennummer=sn", "Label=slot"])
    assert rows[0] == {"host": "pmx30", "sn": "111111274913", "slot": "SSD-1"}
    rows = vault_cmd._table_rows(note, 2, [])
    assert rows[0] == {"host": "pmx30", "id": "101", "name": "testvm", "ip": "192.0.2.101"}


def _record_history() -> int:
    head = Image.new("1", (P.head_dots, 50), 255)
    ImageDraw.Draw(head).rectangle((10, 10, 60, 30), fill=0)
    with HistoryStore(paths.history_db_path()) as store:
        return store.record(JobMeta(source="cli", kind="template", title="T", template="datentraeger",
                                    values={"host": "pmx30", "slot": "SSD-1", "sn": "111111274913"}),
                            landscape=None, head=head, length_mm=20.0, tape_mm=12.0, status="ok")


def test_snippet_copy_png_and_append(fake, monkeypatch, tmp_path, capsys):
    entry_id = _record_history()
    copied = []
    monkeypatch.setattr(vault_cmd, "CLIP_BACKEND", copied.append)
    png = tmp_path / "out" / "s.png"
    assert cli.main(["vault", "snippet", "--kopieren", "--png", str(png), "--an", "Hosts/pmx30"]) == 0
    out = capsys.readouterr().out
    assert len(copied) == 1
    assert copied[0].startswith("- ") and "pmx30 · SSD-1 · SN 274913 ![[label-" in copied[0]
    assert copied[0] in out
    assert png.is_file()
    assert _appends(fake) == [{"path": "Hosts/pmx30", "content": "\n" + copied[0]}]
    assert f"-{entry_id}.png" in copied[0]


def test_snippet_anhang(fake, tmp_path, capsys):
    _record_history()
    assert cli.main(["vault", "snippet", "--anhang"]) == 0
    assert "obsidian.vault_dir ist nicht gesetzt" in capsys.readouterr().err
    write_homelab({"obsidian": {"vault_dir": str(tmp_path / "vault")}})
    assert cli.main(["vault", "snippet", "--anhang"]) == 0
    assert list((tmp_path / "vault" / "Anhänge" / "Labels").glob("label-*.png"))
    assert cli.main(["vault", "snippet", "--anhang", "--an", "Privat/x"]) == 1
    assert fake.requests == []


def test_snippet_errors(fake, monkeypatch, capsys):
    assert cli.main(["vault", "snippet"]) == 1
    assert "Kein gedrucktes Label mit Bild im Verlauf" in capsys.readouterr().err
    _record_history()

    def busy(_text):
        raise OSError("belegt")

    monkeypatch.setattr(vault_cmd, "CLIP_BACKEND", busy)
    assert cli.main(["vault", "snippet", "--kopieren"]) == 1
    assert "Zwischenablage" in capsys.readouterr().err


def test_not_reachable_exit_5(monkeypatch, capsys):
    monkeypatch.setattr(vault_cmd, "TRANSPORT", connect_error_transport())
    assert cli.main(["vault", "list"]) == 5
    err = capsys.readouterr().err
    assert "Obsidian" in err and "Hinweis:" in err
