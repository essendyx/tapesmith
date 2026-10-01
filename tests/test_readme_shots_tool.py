"""`tools/readme_shots.py`: Aufnahmeliste und Rahmen der README-Bilder (ohne Browser)."""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import readme_shots  # noqa: E402


def test_aufnahmen_eindeutig_und_ohne_deutsche_demo_texte():
    names = [shot.name for shot in readme_shots.SHOTS]
    assert len(names) == len(set(names))
    assert {"quick-print", "quick-print-dark", "templates"} <= set(names)
    texts = [readme_shots.QUICK_TEXT, readme_shots.DOCUMENT_NAME, readme_shots.TEMPLATE_VALUES]
    texts += [" ".join(lines) for lines, _days in readme_shots.HISTORY_PLAIN]
    texts += [msg for *_rest, msg in readme_shots.LOG_LINES]
    for text in texts:
        for german in ("ä", "ö", "ü", "ß", "Keller", "Kabel", "Aufbewahrung"):
            assert german not in text, text


def test_rahmen_rundet_ab_und_skaliert(tmp_path):
    raw = tmp_path / "raw.png"
    Image.new("RGB", (800, 500), (255, 255, 255)).save(raw)
    out = tmp_path / "out.png"
    readme_shots.frame(raw, out, "hell", width=600)
    img = Image.open(out).convert("RGB")
    assert img.width == 600
    # Ecke des Hintergrunds ist der Verlauf, nicht das weiße Bild
    assert img.getpixel((2, 2)) != (255, 255, 255)
    assert out.stat().st_size < readme_shots.MAX_BYTES
