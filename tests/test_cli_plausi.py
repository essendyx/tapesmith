"""CLI-Befehle `p12 plausi` und `p12 asset-notiz`."""

import json
import time

import pytest

from obsidian_fakes import FakeMcp
from tapesmith import cli
from tapesmith.cli_cmds import asset_notiz as asset_notiz_cmd
from tapesmith.cli_cmds import plausi as plausi_cmd
from tapesmith.integrations import scancache
from tapesmith.integrations.assets import AssetStore
from tapesmith.sshscan import DiskRow

# Integrationen im Produkt ohne Standardadressen: Tests nutzen neutrale Testadressen.
pytestmark = pytest.mark.usefixtures("homelab_test_defaults")


@pytest.fixture(autouse=True)
def no_real_dns(monkeypatch):
    # Nie echte DNS-Abfragen in Tests: RESOLVER immer injiziert.
    monkeypatch.setattr(plausi_cmd, "RESOLVER", lambda host: [])


def _disk(host, device, serial):
    return DiskRow(host=host, device=device, model="Model X", serial=serial, size="1T", tran="sata",
                   wwn="", by_id=None, pool=None, vdev=None)


def test_plausi_shows_conflict_exit_0(app_home, capsys):
    scancache.save_scan("pmx20", [_disk("pmx20", "sdb", "ABC123DEF456")])
    code = cli.main(["plausi", "datentraeger", "host=pmx10", "sn=ABC123DEF456"])
    out = capsys.readouterr().out
    assert code == 0
    assert "konflikt" in out
    assert "pmx20" in out


def test_plausi_streng_gives_exit_1_on_conflict(app_home, capsys):
    scancache.save_scan("pmx20", [_disk("pmx20", "sdb", "ABC123DEF456")])
    code = cli.main(["plausi", "datentraeger", "host=pmx10", "sn=ABC123DEF456", "--streng"])
    capsys.readouterr()
    assert code == 1


def test_plausi_streng_without_conflict_exit_0(app_home, capsys):
    code = cli.main(["plausi", "datentraeger", "sn=UNBEKANNT", "--streng"])
    capsys.readouterr()
    assert code == 0


def test_plausi_json_output(app_home, capsys):
    scancache.save_scan("pmx10", [_disk("pmx10", "sda", "ANDERESN")])
    code = cli.main(["plausi", "datentraeger", "sn=UNBEKANNT", "--json"])
    out = capsys.readouterr().out
    assert code == 0
    data = json.loads(out)
    assert data["worst"] == "info"
    assert data["findings"][0]["code"] == "sn_unbekannt"


def test_plausi_unknown_template_exit_6(app_home, capsys):
    code = cli.main(["plausi", "gibtsnicht", "sn=X"])
    err = capsys.readouterr().err
    assert code == 6
    assert "gibtsnicht" in err


def test_plausi_broken_asset_register_gives_info_not_traceback(app_home, capsys):
    from tapesmith.integrations import settings

    path = settings.data_dir() / "assets.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"das ist keine sqlite-datei")
    code = cli.main(["plausi", "datentraeger", "sn=X", "--json"])
    out = capsys.readouterr().out
    assert code == 0
    data = json.loads(out)
    messages = [f["message"] for f in data["findings"] if f["code"] == "quelle_fehlt"]
    assert any("Asset-Register" in m for m in messages)

def test_asset_notiz_creates_note_and_prints_path(app_home, monkeypatch, capsys):
    written = {}
    fake = FakeMcp({"vault_write": lambda args: written.update(args) or "ok"})
    monkeypatch.setattr(asset_notiz_cmd, "TRANSPORT", fake.transport())
    with AssetStore() as store:
        store.add_existing("HL-0001", bezeichnung="Patchkabel", standort="Keller")

    code = cli.main(["asset-notiz", "HL-0001"])
    out = capsys.readouterr().out
    assert code == 0
    assert out.strip() == "Assets/HL-0001"
    assert written["path"] == "Assets/HL-0001"


def test_asset_notiz_unknown_id_exit_1(app_home, monkeypatch, capsys):
    fake = FakeMcp({})
    monkeypatch.setattr(asset_notiz_cmd, "TRANSPORT", fake.transport())
    code = cli.main(["asset-notiz", "HL-9999"])
    err = capsys.readouterr().err
    assert code == 1
    assert "HL-9999" in err


def test_timed_resolver_returns_within_timeout_even_if_resolver_hangs():
    """Ein hängender Resolver darf die Antwortzeit nicht über das Zeitlimit hinaus verzögern
    (gleicher Fix wie in routes_plausi._timed_resolver, siehe dortiger Testkommentar)."""

    def hanging_resolver(host: str) -> list[str]:
        time.sleep(3.0)
        return ["should-not-be-seen"]

    timed = plausi_cmd._timed_resolver(hanging_resolver, 0.5)

    start = time.monotonic()
    result = timed("pmx10")
    elapsed = time.monotonic() - start

    assert result == []
    assert elapsed < 1.5, f"_timed_resolver blockierte {elapsed:.2f}s, sollte nach ~0.5s zurückkehren"
