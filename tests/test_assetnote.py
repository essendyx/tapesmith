"""Vault-Notiz aus einem Asset."""

import copy
from datetime import date

import pytest

from obsidian_fakes import MCP_URL, FakeMcp
from tapesmith.integrations import settings
from tapesmith.integrations.assetnote import create_note, note_markdown, note_path, paperless_document_url
from tapesmith.integrations.assets import Asset
from tapesmith.integrations.obsidian import VaultClient

# Integrationen im Produkt ohne Standardadressen: Tests nutzen neutrale Testadressen.
pytestmark = pytest.mark.usefixtures("homelab_test_defaults")

TODAY = date(2026, 9, 28)


def _asset(**kw) -> Asset:
    base = dict(id="HL-0042", bezeichnung="Patchkabel Cat6 3m", kategorie="Netzwerk",
               standort="Keller Rack", seriennummer="ABC123", host="pmx10", ziel="https://x.example/a",
               paperless_doc=17, status="aktiv", notiz="", created="2026-09-28T09:00:00",
               updated="2026-09-28T09:00:00")
    base.update(kw)
    return Asset(**base)


def _write_handler(existing: set[str]):
    def handler(args: dict):
        if args["path"] in existing and not args["overwrite"]:
            return {"content": [{"type": "text", "text": f"Notiz {args['path']} existiert bereits"}],
                    "isError": True}
        existing.add(args["path"])
        return "ok"
    return handler


def test_note_path():
    assert note_path("HL-0042") == "Assets/HL-0042"


def test_note_markdown_full_form():
    md = note_markdown(_asset(), short_link="HTTPS://L.EXAMPLE.COM/HL-0042",
                       paperless_url="http://192.0.2.12:8010/documents/17/details", today=TODAY)
    expected = (
        "# HL-0042 · Patchkabel Cat6 3m\n"
        "\n"
        "- **Asset:** HL-0042\n"
        "- **Bezeichnung:** Patchkabel Cat6 3m\n"
        "- **Kategorie:** Netzwerk\n"
        "- **Standort:** Keller Rack\n"
        "- **Seriennummer:** ABC123\n"
        "- **Host:** [[Hosts/pmx10]]\n"
        "- **Kurz-Link:** HTTPS://L.EXAMPLE.COM/HL-0042\n"
        "- **Rechnung:** [Paperless-Dokument 17](http://192.0.2.12:8010/documents/17/details)\n"
        "- **Status:** aktiv\n"
        "- **Angelegt:** 2026-09-28 (tapesmith)\n"
    )
    assert md == expected


def test_note_markdown_without_paperless_and_short_link_omits_lines():
    md = note_markdown(_asset(seriennummer="", host=""), short_link=None, paperless_url=None, today=TODAY)
    assert "Kurz-Link" not in md
    assert "Rechnung" not in md
    assert "Seriennummer" not in md
    assert "Host:" not in md
    assert md.startswith("# HL-0042 · Patchkabel Cat6 3m\n\n- **Asset:** HL-0042\n")
    assert md.rstrip("\n").endswith("- **Angelegt:** 2026-09-28 (tapesmith)")


def test_paperless_document_url_prefers_public_url():
    data = {"paperless": {"url": "http://192.0.2.12:8010", "public_url": "https://paperless.example.com"}}
    assert paperless_document_url(data, 17) == "https://paperless.example.com/documents/17/details"


def test_paperless_document_url_falls_back_to_url():
    data = {"paperless": {"url": "http://192.0.2.12:8010/", "public_url": None}}
    assert paperless_document_url(data, 17) == "http://192.0.2.12:8010/documents/17/details"


def test_create_note_writes_without_overwrite_to_assets_folder():
    data = copy.deepcopy(settings.DEFAULTS)   # obsidian.folders Standard ["Hosts", "Dienste"], ohne "Assets"
    fake = FakeMcp({"vault_write": _write_handler(set())})
    with VaultClient.from_settings(data, transport=fake.transport()) as vault:
        path = create_note(vault, data, _asset(), today=TODAY)
    assert path == "Assets/HL-0042"
    assert fake.tool_calls[-1][0] == "vault_write"
    args = fake.tool_calls[-1][1]
    assert args["path"] == "Assets/HL-0042"
    assert args["overwrite"] is False


def test_create_note_raises_value_error_if_note_exists():
    data = copy.deepcopy(settings.DEFAULTS)
    fake = FakeMcp({"vault_write": _write_handler({"Assets/HL-0042"})})
    with VaultClient.from_settings(data, transport=fake.transport()) as vault:
        with pytest.raises(ValueError, match="existiert bereits"):
            create_note(vault, data, _asset(), today=TODAY)


def test_create_note_respects_client_folders_without_mcp_call():
    fake = FakeMcp({"vault_write": _write_handler(set())})
    with VaultClient(MCP_URL, transport=fake.transport(), folders=("Hosts",)) as vault:
        with pytest.raises(ValueError, match="außerhalb der freigegebenen Ordner"):
            create_note(vault, settings.DEFAULTS, _asset(), today=TODAY)
    assert fake.requests == []
