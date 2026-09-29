"""Gebaute Web-Oberfläche (Vite-Build aus `web/`), ausgeliefert vom Druckdienst."""

from pathlib import Path


def static_dir() -> Path:
    """Ordner mit `index.html` und `assets/` (kann fehlen, solange nicht gebaut)."""
    return Path(__file__).with_name("static")
