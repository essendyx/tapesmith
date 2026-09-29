"""CLI `p12 proxmox` (hosts, list, print). Nie echter Druck, nie echtes Netz."""

import json

import httpx
import pytest

from homelab_fakes import mock_transport
from tapesmith import cli
from tapesmith.cli_cmds import proxmox as proxmox_cmd
from test_routes_proxmox import _homelab
from test_proxmox import _routes

# Integrationen im Produkt ohne Standardadressen: Tests nutzen neutrale Testadressen.
pytestmark = pytest.mark.usefixtures("homelab_test_defaults")


@pytest.fixture
def pve(tmp_path, monkeypatch):
    calls: list[httpx.Request] = []

    def setup(*, token=True, shortlink=False, sl_routes=None):
        _homelab(tmp_path, token=token, shortlink=shortlink)
        monkeypatch.setattr(proxmox_cmd, "TRANSPORT", mock_transport(_routes(), calls=calls))
        monkeypatch.setattr(proxmox_cmd, "SHORTLINK_TRANSPORT", mock_transport(sl_routes or {}, calls=calls))
        return calls

    return setup


def test_proxmox_in_help(capsys):
    try:
        cli.main(["--help"])
    except SystemExit:
        pass
    assert "proxmox" in capsys.readouterr().out


def test_hosts(pve, capsys):
    pve(token=False)
    assert cli.main(["proxmox", "hosts"]) == 0
    out = capsys.readouterr().out
    assert "pmx10" in out and "https://192.0.2.60:8006" in out and "fehlt" in out


def test_list(pve, capsys):
    calls = pve()
    assert cli.main(["proxmox", "list", "pmx10"]) == 0
    captured = capsys.readouterr()
    assert "webapp1" in captured.out and ".39" in captured.out
    assert "IP unbekannt: gestoppt" in captured.out
    assert "hostpci0" in captured.out
    assert "TLS-Zertifikat von pmx10 wird nicht geprüft" in captured.err
    assert all(c.method == "GET" for c in calls)


def test_list_filters_and_json(pve, capsys):
    pve()
    assert cli.main(["proxmox", "list", "pmx10", "--typ", "lxc", "--status", "running", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert [g["vmid"] for g in data["guests"]] == [102, 103]
    assert data["guests"][0]["ip_kurz"] == ".47"


def test_print_dry_run(pve, capsys):
    pve()
    assert cli.main(["proxmox", "print", "pmx10", "--ids", "111", "--dry-run"]) == 0
    captured = capsys.readouterr()
    assert "1 Label" in captured.out
    assert "unbekannte Felder" not in captured.err
    assert "Keine druckbaren Zeilen" not in captured.err


def test_print_preview(pve, tmp_path, capsys):
    pve()
    preview = tmp_path / "p.png"
    assert cli.main(["proxmox", "print", "pmx10", "--ids", "111", "--preview", str(preview)]) == 0
    assert preview.is_file()


def test_print_rows_passed_uncut(pve, monkeypatch, capsys):
    pve()
    seen = {}

    def fake_print_rows(ctx, args, template, rows, **kw):
        seen["template"] = template
        seen["rows"] = list(rows)
        return 0

    monkeypatch.setattr(proxmox_cmd.cliprint, "print_rows", fake_print_rows)
    assert cli.main(["proxmox", "print", "pmx10", "--ids", "111", "--dry-run"]) == 0
    assert seen["template"] == "vm-lxc"
    assert seen["rows"] == [{"typ": "VM", "vmid": "111", "name": "webapp1", "ip_kurz": ".39",
                             "ip": "192.0.2.39", "node": "pmx10", "host": "pmx10", "link": ""}]


def test_print_links_uses_qr_template(pve, monkeypatch, capsys):
    pve()
    seen = {}

    def fake_print_rows(ctx, args, template, rows, **kw):
        seen["template"] = template
        seen["rows"] = list(rows)
        return 0

    monkeypatch.setattr(proxmox_cmd.cliprint, "print_rows", fake_print_rows)
    assert cli.main(["proxmox", "print", "pmx10", "--ids", "111", "--links", "--dry-run"]) == 0
    assert seen["template"] == "vm-lxc-qr"
    assert seen["rows"][0]["link"] == "https://192.0.2.60:8006/#v1:0:=qemu%2F111"
    assert "Kurz-Link-Dienst nicht eingerichtet" in capsys.readouterr().err


def test_print_links_real_dry_run(pve, capsys):
    pve()
    assert cli.main(["proxmox", "print", "pmx10", "--ids", "111", "--links", "--dry-run"]) == 0
    captured = capsys.readouterr()
    assert "1 Label" in captured.out
    assert "Keine druckbaren Zeilen" not in captured.err


def test_print_links_with_shortlink(pve, monkeypatch, capsys):
    def put(request):
        return httpx.Response(200, json={"id": "PMX10-111", "target": "x", "note": "", "created": "",
                                         "updated": "", "hits": 0})

    pve(shortlink=True, sl_routes={"PUT /api/links/PMX10-111": put})
    seen = {}
    monkeypatch.setattr(proxmox_cmd.cliprint, "print_rows",
                        lambda ctx, args, template, rows, **kw: seen.update(rows=list(rows)) or 0)
    assert cli.main(["proxmox", "print", "pmx10", "--ids", "111", "--links", "--dry-run"]) == 0
    assert seen["rows"][0]["link"] == "HTTPS://L.EXAMPLE.COM/PMX10-111"


def test_print_no_match_is_exit_1(pve, capsys):
    pve()
    assert cli.main(["proxmox", "print", "pmx10", "--ids", "999", "--dry-run"]) == 1
    assert "Keine Gäste" in capsys.readouterr().err


def test_unknown_host_exit_1(pve, capsys):
    pve()
    assert cli.main(["proxmox", "list", "pmx30"]) == 1
    assert "pmx30" in capsys.readouterr().err


def test_token_missing_exit_1(pve, capsys):
    pve(token=False)
    assert cli.main(["proxmox", "list", "pmx10"]) == 1
    assert "Token fehlt" in capsys.readouterr().err
