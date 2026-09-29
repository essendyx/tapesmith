"""Mitgelieferte Schriften (DejaVu 2.37). Kein stiller Ersatz: fehlt eine Schrift, gibt es einen Fehler."""

import io
from functools import lru_cache
from importlib import resources
from pathlib import Path

from PIL import ImageFont
from tapesmith.i18n import _t

FONT_FILES = {
    "sans": "DejaVuSans.ttf",
    "sans-bold": "DejaVuSans-Bold.ttf",
    "mono": "DejaVuSansMono.ttf",
}


class FontMissing(RuntimeError):
    pass


def font_path(name: str) -> Path:
    """Pfad der Schriftdatei im Paket, nur im Quellbaum verlässlich (Entwicklung/Tests);
    in Zip-/frozen-Builds `font_bytes` verwenden."""
    if name not in FONT_FILES:
        raise FontMissing(_t("Unbekannte Schrift '{name}' (verfügbar: {items})", name=name, items=', '.join(FONT_FILES)))
    path = Path(str(resources.files("tapesmith.fonts").joinpath(FONT_FILES[name])))
    if not path.is_file():
        raise FontMissing(_t("Schriftdatei fehlt: {path}. tools/fetch_fonts.py ausführen", path=path))
    return path


@lru_cache(maxsize=8)
def font_bytes(name: str) -> bytes:
    """Schriftdaten als Bytes über `importlib.resources`; funktioniert auch aus Zip/frozen."""
    if name not in FONT_FILES:
        raise FontMissing(_t("Unbekannte Schrift '{name}' (verfügbar: {items})", name=name, items=', '.join(FONT_FILES)))
    try:
        return resources.files("tapesmith.fonts").joinpath(FONT_FILES[name]).read_bytes()
    except (FileNotFoundError, OSError) as exc:
        raise FontMissing(_t("Schriftdatei fehlt: {value}. tools/fetch_fonts.py ausführen", value=FONT_FILES[name])) from exc


@lru_cache(maxsize=512)
def load_font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(io.BytesIO(font_bytes(name)), size)
