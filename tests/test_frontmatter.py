"""Frontmatter- und Markdown-Parser ohne PyYAML."""

from obsidian_fakes import data_text
from tapesmith.integrations.frontmatter import (MdTable, bold_bullets, first_heading, normalize_key,
                                               split_frontmatter, strip_markdown, tables)


def test_split_frontmatter_lists_and_quotes():
    meta, body = split_frontmatter(data_text("dienst-mit-frontmatter.md"))
    assert meta["host"] == "docker99"
    assert meta["ip"] == "192.0.2.98"
    assert meta["tags"] == "a, b"
    assert meta["port"] == "8080"
    assert meta["aliase"] == "erster, zweiter"
    assert "meta" not in meta and "tief" not in meta
    assert body.startswith("# Testdienst")


def test_split_frontmatter_without():
    text = data_text("pmx30.md")
    assert split_frontmatter(text) == ({}, text)
    assert split_frontmatter("---\nnicht geschlossen\n") == ({}, "---\nnicht geschlossen\n")


def test_split_frontmatter_crlf_and_single_quotes():
    meta, body = split_frontmatter("---\r\nname: 'x y'\r\nleer:\r\n---\r\nText")
    assert meta == {"name": "x y", "leer": ""}
    assert body == "Text"


def test_normalize_key():
    assert normalize_key("IP") == "ip"
    assert normalize_key("Kernel-Header") == "kernel_header"
    assert normalize_key("Größe") == "groesse"
    assert normalize_key("  Über  Äpfel!! ") == "ueber_aepfel"
    assert normalize_key("VM-ID (Proxmox)") == "vm_id_proxmox"


def test_strip_markdown():
    assert strip_markdown("[[Hosts/kvm01|KVM01]] und `x`") == "KVM01 und x"
    assert strip_markdown("**fett** [[Dienste/n8n]] [Link](https://x) ⚠️") == "fett n8n Link ⚠️"
    assert strip_markdown("  __a__ *b* ") == "a b"
    assert strip_markdown("[[Dienste/x\\|Alias]]") == "Alias"


def test_bold_bullets_on_pmx30():
    values = bold_bullets(data_text("pmx30.md"))
    assert values["ip"].startswith("192.0.2.99 · WebUI https://192.0.2.99:8006/")
    assert values["version"] == "pve-manager 9.2.x"
    assert values["platten"] == "2× Testplatte 256 GB"
    assert values["doku"] == "siehe Testdienst"
    assert "unterpunkt" not in values


def test_bold_bullets_first_wins():
    assert bold_bullets("- **A:** 1\n* **a**: 2\n") == {"a": "1"}


def test_tables_on_pmx30():
    found = tables(data_text("pmx30.md"))
    assert len(found) == 2
    first, second = found
    assert isinstance(first, MdTable)
    assert first.heading == "Platten"
    assert first.headers == ("Label", "Seriennummer", "Rolle")
    assert first.rows == (("SSD-1", "111111274913", "rpool Spiegel"),
                          ("SSD-2", "222222274988", "rpool Spiegel"))
    assert second.heading == "Gäste"
    assert second.headers == ("ID", "Name", "IP")
    assert second.rows[1] == ("102", "testlxc", "192.0.2.102")
    assert second.rows[2] == ("103", "kurz", "")


def test_tables_without_heading_and_truncation():
    text = "Text\n\n| a | b |\n| --- | --- |\n| 1 | 2 | 3 |\n\n| kein | trenner |\n| x | y |\n"
    found = tables(text)
    assert len(found) == 1
    assert found[0].heading is None
    assert found[0].rows == (("1", "2"),)


def test_first_heading():
    assert first_heading(data_text("pmx30.md")) == "pmx30 · Proxmox VE (Testserver)"
    assert first_heading("## nur H2\n") is None
    assert first_heading("---\ntitle: x\n---\n# Titel\n") == "Titel"
