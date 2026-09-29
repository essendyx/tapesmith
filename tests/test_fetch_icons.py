"""Tests für tools/fetch_icons.py (Icon-Bibliothek), vollständig offline."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "fetch_icons.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("fetch_icons", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def fi():
    return _load_module()


# ---------- build_tabler_index ----------

def test_build_tabler_index_filters_sorts_and_converts_unicode(fi):
    icons_json = {
        "server": {
            "category": "Devices",
            "tags": ["computer", "database"],
            "styles": {"outline": {"version": "1.0", "unicode": "eb1f"}},
        },
        "a-b-2": {
            "category": "",
            "tags": ["test", None],
            "styles": {"outline": {"version": "1.76", "unicode": "f25f"}},
        },
        "no-outline": {
            "category": "Misc",
            "tags": [],
            "styles": {},
        },
    }
    result = fi.build_tabler_index(icons_json)
    assert len(result) == 2
    assert [e["name"] for e in result] == ["a-b-2", "server"]
    server = next(e for e in result if e["name"] == "server")
    assert server["unicode"] == 0xEB1F
    assert isinstance(server["unicode"], int)
    assert server["category"] == "Devices"
    assert server["tags"] == ["computer", "database"]
    ab2 = next(e for e in result if e["name"] == "a-b-2")
    assert ab2["tags"] == ["test"]


# ---------- rasterize_svg ----------

def test_rasterize_svg_renders_rect(qtbot, fi):
    svg = (
        b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        b'<rect x="4" y="4" width="16" height="16"/></svg>'
    )
    image = fi.rasterize_svg(svg, 64)
    assert image.mode == "L"
    assert image.size == (64, 64)
    assert image.getpixel((32, 32)) < 64
    assert image.getpixel((2, 2)) > 200


# ---------- helpers ----------

def test_extract_svg_title(fi):
    svg = b'<svg role="img" viewBox="0 0 24 24"><title>Proxmox</title><path d="M0 0"/></svg>'
    assert fi._extract_svg_title(svg) == "Proxmox"
    assert fi._extract_svg_title(b"<svg></svg>") is None
