import pytest

from tapesmith.render.fonts import FONT_FILES, FontMissing, font_path, load_font


def test_all_bundled_fonts_exist():
    assert set(FONT_FILES) == {"sans", "sans-bold", "mono"}
    for name in FONT_FILES:
        assert font_path(name).is_file()


def test_load_font_is_cached_and_sized():
    a = load_font("sans", 40)
    assert a is load_font("sans", 40)
    assert a.size == 40


def test_unknown_font_is_explicit_error():
    with pytest.raises(FontMissing, match="verfügbar"):
        font_path("comic")


def test_missing_file_is_explicit_error(monkeypatch):
    monkeypatch.setitem(FONT_FILES, "sans", "Fehlt.ttf")
    with pytest.raises(FontMissing, match="fehlt"):
        font_path("sans")
