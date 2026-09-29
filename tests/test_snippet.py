"""Vault-Snippet aus dem Verlauf und Rückkanal nach dem Druck."""

import copy
import io
import re
from datetime import date, datetime

import pytest
from PIL import Image, ImageDraw

from obsidian_fakes import MCP_URL, FakeMcp, vault_tools
from tapesmith.device.profile import load_profile
from tapesmith.history import HistoryStore
from tapesmith.integrations import settings, snippet
from tapesmith.integrations.obsidian import VaultClient
from tapesmith.jobs import JobMeta

P = load_profile()
CREATED = datetime(2026, 9, 26, 10, 15, 0)
VALUES = {"host": "pmx30", "slot": "SSD-1", "sn": "111111274913"}


def make_head() -> Image.Image:
    head = Image.new("1", (P.head_dots, 60), 255)
    ImageDraw.Draw(head).rectangle((20, 10, 70, 40), fill=0)
    return head


def record(store: HistoryStore, *, values=None, head=True, title="Datenträger") -> int:
    meta = JobMeta(source="api", kind="template", title=title, template="datentraeger",
                   values=dict(VALUES if values is None else values))
    return store.record(meta, landscape=None, head=make_head() if head else None, length_mm=20.0,
                        tape_mm=12.0, status="ok")


@pytest.fixture
def store(tmp_path):
    with HistoryStore(tmp_path / "h.sqlite3", clock=lambda: CREATED) as s:
        yield s


def _data(**obsidian):
    data = copy.deepcopy(settings.DEFAULTS)
    data["obsidian"].update(obsidian)
    return data


def test_summary_rules(store):
    entry = store.get(record(store))
    assert snippet.summary_for(entry) == "pmx30 · SSD-1 · SN 274913"
    assert snippet.summary_from_values({"a": "", "seriennummer": "12345", "b": " x "}, "T") == "SN 12345 · x"
    assert snippet.summary_from_values({}, "Titel") == "Titel"
    assert snippet.summary_from_values({"a": " "}, "Titel") == "Titel"


def test_build_snippet(store):
    entry_id = record(store)
    entry = store.get(entry_id)
    snip = snippet.build_snippet(entry, store.head_image(entry_id), P)
    assert snip.history_id == entry_id
    assert snip.file_name == f"label-20260926-101500-{entry_id}.png"
    image = Image.open(io.BytesIO(snip.png))
    assert image.format == "PNG"
    assert image.mode == "1"
    assert image.getbbox() is not None
    assert snip.summary == "pmx30 · SSD-1 · SN 274913"
    assert snip.markdown == (f"- 2026-09-26 Label gedruckt: pmx30 · SSD-1 · SN 274913 "
                             f"![[label-20260926-101500-{entry_id}.png]]")
    assert re.search(r"!\[\[label-.*\.png\]\]$", snip.markdown)
    assert snip.changelog_md == f"- Label gedruckt: pmx30 · SSD-1 · SN 274913 (Verlauf #{entry_id})"
    other = snippet.build_snippet(entry, store.head_image(entry_id), P, day=date(2026, 9, 28))
    assert other.markdown.startswith("- 2026-09-28 ")


def test_save_attachment_does_not_overwrite(store, tmp_path):
    entry_id = record(store)
    snip = snippet.snippet_for(store, P, entry_id)
    target = tmp_path / "vault" / "Anhänge" / "Labels"
    first = snippet.save_attachment(snip, target)
    second = snippet.save_attachment(snip, target)
    assert first == target / snip.file_name
    assert second == target / snip.file_name.replace(".png", "-2.png")
    third = snippet.save_attachment(snip, target)
    assert third.name.endswith("-3.png")
    assert first.read_bytes() == snip.png == second.read_bytes()


def test_snippet_for_last_and_errors(store):
    with pytest.raises(ValueError, match="Kein gedrucktes Label mit Bild im Verlauf"):
        snippet.snippet_for(store, P, None)
    record(store, head=False)
    with pytest.raises(ValueError, match="Kein gedrucktes Label mit Bild im Verlauf"):
        snippet.snippet_for(store, P, None)
    second = record(store)
    assert snippet.snippet_for(store, P, None).history_id == second
    with pytest.raises(KeyError):
        snippet.snippet_for(store, P, 999)


def test_append_after_print_respects_setting(store, tmp_path):
    fake = FakeMcp(vault_tools())
    day = date(2026, 9, 28)
    with VaultClient(MCP_URL, transport=fake.transport(), folders=("Hosts", "Dienste", "Assets")) as vault:
        off = snippet.append_after_print(vault, _data(), "Hosts/pmx30", "pmx30 · 192.0.2.99", day=day)
        assert off == snippet.AfterPrint(False, None, None, "ausgeschaltet")
        assert fake.requests == []

        on = snippet.append_after_print(vault, _data(append_after_print=True), "Hosts/pmx30",
                                        "pmx30 · 192.0.2.99", day=day)
        assert on.appended is True and on.reason == "" and on.saved_path is None
        assert on.line == "- 2026-09-28 Label gedruckt: pmx30 · 192.0.2.99"
        assert fake.tool_calls == [("vault_append", {"path": "Hosts/pmx30",
                                                     "content": "\n- 2026-09-28 Label gedruckt: pmx30 · 192.0.2.99"})]

        forced = snippet.append_after_print(vault, _data(), "Hosts/pmx30", "x", day=day, force=True)
        assert forced.appended is True
        assert len(fake.tool_calls) == 2

        entry_id = record(store)
        snip = snippet.snippet_for(store, P, entry_id)
        with_png = snippet.append_after_print(vault, _data(append_after_print=True, vault_dir=str(tmp_path)),
                                              "Hosts/pmx30", snip.summary, day=day, snippet=snip)
        assert with_png.line.endswith(f"![[{snip.file_name}]]")
        saved = tmp_path / "Anhänge" / "Labels" / snip.file_name
        assert with_png.saved_path == str(saved)
        assert saved.read_bytes() == snip.png

        no_dir = snippet.append_after_print(vault, _data(append_after_print=True), "Hosts/pmx30",
                                            snip.summary, day=day, snippet=snip)
        assert "![[" not in no_dir.line and no_dir.saved_path is None

        with pytest.raises(ValueError):
            snippet.append_after_print(vault, _data(append_after_print=True), "Privat/x", "x", day=day)
    assert len(fake.tool_calls) == 4


def test_store_attachment_renames_embedding(store, tmp_path):
    snip = snippet.snippet_for(store, P, record(store))
    first, _path = snippet.store_attachment(snip, tmp_path)
    assert first == snip
    second, path = snippet.store_attachment(snip, tmp_path)
    assert second.file_name == path.name and path.name.endswith("-2.png")
    assert second.markdown.endswith(f"![[{path.name}]]")
