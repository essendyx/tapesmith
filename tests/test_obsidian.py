"""Vault-Zugriff über MCP, Werte- und Tabellen-Extraktion, Ordnerfreigabe."""

import copy
from datetime import date

import pytest

from homelab_fakes import connect_error_transport
from obsidian_fakes import MCP_URL, FakeMcp, data_json, data_text, vault_tools
from tapesmith.integrations import obsidian, settings
from tapesmith.integrations.errors import NotReachable
from tapesmith.integrations.obsidian import (VaultClient, VaultHit, allowed_folders, attachment_dir,
                                            note_values, print_line, validate_note_path)

# Integrationen im Produkt ohne Standardadressen: Tests nutzen neutrale Testadressen.
pytestmark = pytest.mark.usefixtures("homelab_test_defaults")


def _client(tools=None, **kw):
    fake = FakeMcp(tools if tools is not None else vault_tools())
    return VaultClient(MCP_URL, transport=fake.transport(), **kw), fake


def test_note_values_from_bold_bullets():
    values = note_values("Hosts/pmx30", data_text("pmx30.md"))
    assert values["ip"] == "192.0.2.99"
    assert values["host"] == "pmx30"
    assert values["name"] == "pmx30"
    assert values["titel"] == "pmx30"
    assert values["pfad"] == "Hosts/pmx30"
    assert values["version"] == "pve-manager 9.2.x"


def test_frontmatter_wins_over_bold_bullets():
    values = note_values("Dienste/testdienst", data_text("dienst-mit-frontmatter.md"))
    assert values["host"] == "docker99"
    assert values["ip"] == "192.0.2.98"
    assert values["port"] == "8080"
    assert values["tags"] == "a, b"
    assert values["name"] == "testdienst"
    assert values["titel"] == "Testdienst"


def test_note_values_ids_and_title_dash():
    text = "# gast1 \u2014 Testgast\n\n- **VMID:** VM 123 (alt 99)\n- **IPv4:** keine\n- **ID:** abc\n"
    values = note_values("Hosts/gast1", text)
    assert values["titel"] == "gast1"
    assert values["vmid"] == "123"
    assert values["ipv4"] == "keine"
    assert values["id"] == "abc"


def test_note_values_without_heading_uses_name():
    assert note_values("Hosts/x", "nur Text")["titel"] == "x"


def test_note_object():
    client, _fake = _client()
    with client:
        note = client.note("Hosts/pmx30.md")
    assert note.path == "Hosts/pmx30"
    assert note.title == "pmx30"
    assert note.values["ip"] == "192.0.2.99"
    assert len(note.tables) == 2
    assert note.text == data_text("pmx30.md")


def test_list_notes_with_list_result():
    client, fake = _client()
    with client:
        assert client.list_notes("Hosts") == ["Hosts/pmx30"]
    assert fake.tool_calls == [("vault_list", {"folder": "Hosts"})]


def test_list_notes_with_text_result():
    text = data_json("mcp-list-text.json")["result"]
    client, _fake = _client({"vault_list": text})
    with client:
        assert client.list_notes("Dienste") == ["Dienste/anderer", "Dienste/testdienst"]
    client, _fake = _client({"vault_list": '["B/y.md", "A/x.md"]'})
    with client:
        assert client.list_notes() == ["A/x", "B/y"]
    client, _fake = _client({"vault_list": [{"path": "A/z.md"}, "A/x.md"]})
    with client:
        assert client.list_notes() == ["A/x", "A/z"]


def test_search_parses_hits_and_ignores_context():
    client, fake = _client()
    with client:
        hits = client.search("192.0.2.99", max_results=5)
    assert hits == [VaultHit("Hosts/pmx30", 3, "- **IP:** 192.0.2.99 · WebUI"),
                    VaultHit("Dienste/testdienst", 12, "Läuft auf 192.0.2.99")]
    assert fake.tool_calls == [("vault_search", {"query": "192.0.2.99", "max_results": 5,
                                                 "context_lines": 0})]


def test_search_grouped_format_and_dash_lines():
    text = "Hosts/pmx30.md\n  3: - **IP:** x\n  L7: y\nDienste/a.md:5-Treffer mit Strich\nkeine Treffer"
    client, _fake = _client({"vault_search": text})
    with client:
        hits = client.search("x")
    assert hits == [VaultHit("Hosts/pmx30", 3, "- **IP:** x"), VaultHit("Hosts/pmx30", 7, "y"),
                    VaultHit("Dienste/a", 5, "Treffer mit Strich")]


def test_append_sends_exact_arguments():
    client, fake = _client()
    with client:
        client.append("Hosts/pmx30.md", "\nZeile")
    assert fake.tool_calls == [("vault_append", {"path": "Hosts/pmx30", "content": "\nZeile"})]


def test_write_and_changelog():
    client, fake = _client()
    with client:
        client.write("Assets/HL-0001", "Inhalt", overwrite=True)
        client.changelog("Label gedruckt", "- x", day=date(2026, 9, 28))
        client.changelog("Ohne Datum", "- y")
    assert fake.tool_calls == [
        ("vault_write", {"path": "Assets/HL-0001", "content": "Inhalt", "overwrite": True}),
        ("changelog_add", {"title": "Label gedruckt", "entry": "- x", "date": "2026-09-28"}),
        ("changelog_add", {"title": "Ohne Datum", "entry": "- y", "date": ""}),
    ]


@pytest.mark.parametrize("bad", ["../x", "Hosts/../x", "/Hosts/x", "\\Hosts\\x", "C:\\x", "C:/x", "", "   ",
                                 "a" * 201])
def test_validate_rejects_bad_form(bad):
    with pytest.raises(ValueError):
        validate_note_path(bad)


def test_validate_folders():
    folders = ["Hosts", "Dienste", "Assets"]
    with pytest.raises(ValueError) as info:
        validate_note_path("Privat/x", folders)
    assert str(info.value) == ("Notiz liegt außerhalb der freigegebenen Ordner: Privat/x "
                               "(erlaubt: Hosts, Dienste, Assets)")
    assert validate_note_path("Assets/HL-0001", folders) == "Assets/HL-0001"
    assert validate_note_path("Hosts/pmx30.md", folders) == "Hosts/pmx30"
    assert validate_note_path(" hosts\\pmx30 ", folders) == "hosts/pmx30"
    assert validate_note_path("Privat/x") == "Privat/x"


def test_allowed_folders_defaults():
    assert allowed_folders(settings.DEFAULTS) == ["Hosts", "Dienste", "Assets"]
    assert VaultClient.from_settings(settings.DEFAULTS).folders == ("Hosts", "Dienste", "Assets")
    data = copy.deepcopy(settings.DEFAULTS)
    data["obsidian"]["folders"] = ["Assets", "Netzwerk"]
    assert allowed_folders(data) == ["Assets", "Netzwerk"]


def test_from_settings_uses_url_and_timeout():
    data = copy.deepcopy(settings.DEFAULTS)
    data["obsidian"]["mcp_url"] = MCP_URL
    data["obsidian"]["timeout_s"] = 3.0
    fake = FakeMcp(vault_tools())
    with VaultClient.from_settings(data, transport=fake.transport()) as client:
        assert client.read("Hosts/pmx30").startswith("# pmx30")
    assert fake.tool_calls == [("vault_read", {"path": "Hosts/pmx30"})]


def test_client_enforces_folders():
    data = copy.deepcopy(settings.DEFAULTS)
    fake = FakeMcp(vault_tools())
    with VaultClient.from_settings(data, transport=fake.transport()) as client:
        for call in (lambda: client.append("Privat/x", "y"), lambda: client.write("Privat/x", "y"),
                     lambda: client.note("Privat/x"), lambda: client.read("Privat/x"),
                     lambda: client.list_notes("Privat"), lambda: client.append("../Hosts/x", "y")):
            with pytest.raises(ValueError):
                call()
        assert fake.requests == []
        client.write("Assets/HL-0001", "Asset")
    assert fake.tool_calls == [("vault_write", {"path": "Assets/HL-0001", "content": "Asset",
                                                "overwrite": False})]

    fake = FakeMcp(vault_tools())
    with VaultClient(MCP_URL, transport=fake.transport()) as client:
        assert client.folders is None
        client.append("Privat/x", "y")
    assert fake.tool_calls == [("vault_append", {"path": "Privat/x", "content": "y"})]


def test_print_line():
    assert print_line(date(2026, 9, 26), "pmx10 · SSD-1 · SN 274913", "label-20260926-101500-7.png") == (
        "- 2026-09-26 Label gedruckt: pmx10 · SSD-1 · SN 274913 ![[label-20260926-101500-7.png]]")
    line = print_line(date(2026, 9, 26), "pmx10")
    assert line == "- 2026-09-26 Label gedruckt: pmx10"
    assert "\u2013" not in line and "\u2014" not in line


def test_attachment_dir(tmp_path):
    data = copy.deepcopy(settings.DEFAULTS)
    assert attachment_dir(data) is None
    data["obsidian"]["vault_dir"] = str(tmp_path)
    assert attachment_dir(data) == tmp_path / "Anhänge" / "Labels"


def test_service_name():
    assert obsidian.SERVICE == "Obsidian"
    assert obsidian.IPV4_RE.search("a 10.1.2.3 b").group(0) == "10.1.2.3"


# ---------------------------------------------------------------- Rückfall auf den lokalen Vault-Ordner

def _local_vault(tmp_path):
    (tmp_path / "Hosts" / "Sub").mkdir(parents=True)
    (tmp_path / "Hosts" / "pmx10.md").write_text(
        "---\nip: 192.0.2.60\nrolle: Hypervisor\n---\n# pmx10 · Proxmox\n\n- **Standort:** Keller\n",
        encoding="utf-8")
    (tmp_path / "Hosts" / "Sub" / "nas.md").write_text("# nas\n", encoding="utf-8")
    (tmp_path / "Privat").mkdir()
    (tmp_path / "Privat" / "geheim.md").write_text("# geheim\n", encoding="utf-8")
    data = copy.deepcopy(settings.DEFAULTS)
    data["obsidian"]["vault_dir"] = str(tmp_path)
    return data


def test_lokaler_rueckfall_liest_notiz_und_frontmatter(tmp_path):
    data = _local_vault(tmp_path)
    with VaultClient.from_settings(data, transport=connect_error_transport()) as client:
        note = client.note("Hosts/pmx10")
        assert client.used_local is True
    assert note.values["ip"] == "192.0.2.60"
    assert note.values["rolle"] == "Hypervisor"
    assert note.values["standort"] == "Keller"
    assert note.title == "pmx10"


def test_lokaler_rueckfall_listet_nur_freigegebene_ordner(tmp_path):
    data = _local_vault(tmp_path)
    with VaultClient.from_settings(data, transport=connect_error_transport()) as client:
        assert client.list_notes("Hosts") == ["Hosts/Sub/nas", "Hosts/pmx10"]
        assert client.list_notes() == ["Hosts/Sub/nas", "Hosts/pmx10"]
        with pytest.raises(ValueError):
            client.read("Privat/geheim")


def test_lokaler_rueckfall_fehlende_notiz_meldet_nicht_erreichbar(tmp_path):
    data = _local_vault(tmp_path)
    with VaultClient.from_settings(data, transport=connect_error_transport()) as client:
        with pytest.raises(NotReachable):
            client.read("Hosts/fehlt")


def test_ohne_vault_dir_kein_rueckfall():
    data = copy.deepcopy(settings.DEFAULTS)
    with VaultClient.from_settings(data, transport=connect_error_transport()) as client:
        with pytest.raises(NotReachable):
            client.read("Hosts/pmx10")
        with pytest.raises(NotReachable):
            client.list_notes("Hosts")


def test_mcp_erreichbar_hat_vorrang_vor_lokalem_ordner(tmp_path):
    data = _local_vault(tmp_path)
    data["obsidian"]["mcp_url"] = MCP_URL
    fake = FakeMcp(vault_tools())
    with VaultClient.from_settings(data, transport=fake.transport()) as client:
        assert client.read("Hosts/pmx30").startswith("# pmx30")
        assert client.used_local is False
