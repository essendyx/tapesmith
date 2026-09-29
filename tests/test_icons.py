"""Tests für tapesmith.render.icons (Icon-Bibliothek)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

from tapesmith.render import icons as icons_mod
from tapesmith.render.icons import (
    IconMissing,
    categories,
    icons_in_category,
    import_user_icon,
    parse_ref,
    render_icon,
    search_icons,
    user_icon_dir,
)

ICONS_DIR = Path(icons_mod.__file__).resolve().parent.parent / "icons"
TTF_PRESENT = (ICONS_DIR / "tabler-icons.ttf").is_file()

pytestmark = pytest.mark.skipif(
    not TTF_PRESENT, reason="tabler-icons.ttf fehlt, tools/fetch_icons.py ausführen"
)


def _all_category_refs():
    data = icons_mod._categories_data()
    refs = []
    for key, value in data.items():
        if key == "synonyme":
            for syn_refs in value.values():
                refs.extend(syn_refs)
        else:
            refs.extend(value)
    return refs


# ---------- 3. Alle Kategorie-/Synonym-Referenzen sind renderbar ----------

def test_all_category_and_synonym_refs_are_renderable():
    refs = _all_category_refs()
    assert refs, "categories.json sollte Referenzen enthalten"
    for ref in refs:
        image = render_icon(ref, 32)
        assert image.size == (32, 32)


# ---------- 4. Tabler-Glyph mittig, Modus 1 ----------

def test_render_icon_tabler_server_centered():
    image = render_icon("tabler:server", 40)
    assert image.mode == "1"
    assert image.size == (40, 40)
    colors = set(v for _c, v in image.getcolors())
    assert colors == {0, 255} or colors <= {0, 255}
    assert 0 in colors and 255 in colors

    inverted = image.point(lambda p: 255 - p)
    bbox = inverted.getbbox()
    assert bbox is not None
    cx = (bbox[0] + bbox[2]) / 2
    cy = (bbox[1] + bbox[3]) / 2
    assert abs(cx - 20) <= 3
    assert abs(cy - 20) <= 3


# ---------- 5. Größen ----------

@pytest.mark.parametrize("size", [8, 16, 88])
def test_render_icon_sizes(size):
    image = render_icon("tabler:server", size)
    assert image.size == (size, size)


def test_render_icon_too_small_raises():
    with pytest.raises(ValueError):
        render_icon("tabler:server", 7)


# ---------- 6. Unbekanntes Icon / ungültige Form ----------

def test_render_icon_unknown_tabler_icon():
    with pytest.raises(IconMissing):
        render_icon("tabler:gibtsnicht", 32)


def test_render_icon_invalid_form():
    with pytest.raises(IconMissing):
        render_icon("foo", 32)


def test_parse_ref_valid():
    assert parse_ref("tabler:server") == ("tabler", "server")


def test_parse_ref_invalid():
    with pytest.raises(IconMissing, match="ungültig"):
        parse_ref("foo")


# ---------- 7. Suche ----------

def test_search_icons_exact_match_first():
    result = search_icons("server")
    assert result
    assert result[0].ref == "tabler:server"


def test_search_icons_synonym():
    result = search_icons("strom")
    refs = {icon.ref for icon in result}
    assert refs & {"tabler:bolt", "tabler:plug"}


def test_search_icons_empty_query_in_category():
    assert [icon.ref for icon in search_icons("", category="Warnung")] == [
        icon.ref for icon in icons_in_category("Warnung")
    ]


# ---------- 8. Marken / Simple Icons ----------

def test_icons_in_category_marken_contains_proxmox_or_any_simple():
    marken = icons_in_category("Marken")
    refs = {icon.ref for icon in marken}
    if "simple:proxmox" in refs:
        assert "simple:proxmox" in refs
    else:
        assert any(ref.startswith("simple:") for ref in refs)


def test_render_icon_simple_has_ink():
    image = render_icon("simple:proxmox", 48)
    inverted = image.point(lambda p: 255 - p)
    assert inverted.getbbox() is not None


# ---------- 9. Eigene Icons ----------

def test_import_user_icon_roundtrip():
    ref1 = import_user_icon(Image.new("RGBA", (100, 50), (0, 0, 0, 255)), "Mein Logo")
    assert ref1 == "user:mein-logo"
    assert (user_icon_dir() / "mein-logo.png").is_file()

    ref2 = import_user_icon(Image.new("RGBA", (100, 50), (0, 0, 0, 255)), "Mein Logo")
    assert ref2 == "user:mein-logo-2"

    assert categories()[-1] == "Eigene"
    image = render_icon("user:mein-logo", 32)
    assert image.size == (32, 32)


def test_import_user_icon_empty_name_raises():
    with pytest.raises(ValueError):
        import_user_icon(Image.new("RGBA", (10, 10), (0, 0, 0, 255)), "   ")


# ---------- 10. Lizenzdateien ----------

def test_license_files_present():
    tabler_license = (ICONS_DIR / "LICENSE-tabler.txt").read_text(encoding="utf-8")
    assert "MIT License" in tabler_license
    simple_license = (ICONS_DIR / "simple" / "LICENSE-simple-icons.txt").read_text(encoding="utf-8")
    assert "CC0" in simple_license
    assert (ICONS_DIR / "simple" / "MARKEN.txt").is_file()


# ---------- 11. Kein Qt im Kern ----------

def test_no_qt_import_in_core():
    code = "import sys; import tapesmith.render.icons; print('PySide6' in sys.modules)"
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False"
