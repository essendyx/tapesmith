"""Lädt Tabler Icons (MIT, ~5000 Symbole) als Icon-Font und ausgewählte Simple Icons
(CC0, Markenrechte beachten) als 256-px-Graustufenmasken; legt beides als Paketdaten an.

Idempotent: vorhandene Dateien werden ohne --force nicht erneut geladen.
Aufruf: .venv\\Scripts\\python tools\\fetch_icons.py [--force]
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import urllib.request
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

TABLER_VERSION = "3.35.0"
TABLER_TTF_URL = (
    f"https://cdn.jsdelivr.net/npm/@tabler/icons-webfont@{TABLER_VERSION}/dist/fonts/tabler-icons.ttf"
)
TABLER_JSON_URL = f"https://cdn.jsdelivr.net/npm/@tabler/icons@{TABLER_VERSION}/icons.json"
TABLER_LICENSE_URL = f"https://cdn.jsdelivr.net/npm/@tabler/icons-webfont@{TABLER_VERSION}/LICENSE"

SIMPLE_ICONS_PREFERRED_VERSION = "13.21.0"
SIMPLE_ICONS_VERSIONS_URL = "https://data.jsdelivr.com/v1/package/npm/simple-icons"
SIMPLE_ICON_SVG_URL = "https://cdn.jsdelivr.net/npm/simple-icons@{version}/icons/{slug}.svg"
SIMPLE_ICON_LICENSE_URL = "https://cdn.jsdelivr.net/npm/simple-icons@{version}/LICENSE.md"

SIMPLE_ICON_SLUGS = [
    "proxmox", "docker", "debian", "ubuntu", "linux", "raspberrypi", "homeassistant",
    "truenas", "opnsense", "pfsense", "nextcloud", "grafana", "cloudflare", "tailscale",
    "wireguard", "synology", "paperlessngx", "obsidian", "jellyfin", "nginx",
]

TARGET = Path(__file__).resolve().parent.parent / "src" / "tapesmith" / "icons"
SIMPLE_TARGET = TARGET / "simple"

MARKEN_TEXT = (
    "Simple Icons steht unter der CC0-1.0-Lizenz (gemeinfrei). Die abgebildeten Logos\n"
    "sind trotzdem Marken ihrer jeweiligen Inhaber. Sie werden hier ausschließlich zur\n"
    "Kennzeichnung eigener Geräte und Dienste verwendet, nicht für Werbung und nicht,\n"
    "um eine Zugehörigkeit zum Markeninhaber vorzutäuschen.\n"
)


def build_tabler_index(icons_json: dict) -> list[dict]:
    """icons_json: Rohinhalt von icons.json ({"name": {"category", "tags", "styles": {...}}, ...}).

    Liefert je Icon mit `styles.outline.unicode` einen Eintrag
    {"name", "unicode": int, "category", "tags": [...]}, sortiert nach Name.
    """
    entries = []
    for name, info in icons_json.items():
        outline = (info.get("styles") or {}).get("outline") or {}
        unicode_hex = outline.get("unicode")
        if not unicode_hex:
            continue
        entries.append(
            {
                "name": name,
                "unicode": int(unicode_hex, 16),
                "category": info.get("category", ""),
                "tags": [t for t in info.get("tags", []) if isinstance(t, str)],
            }
        )
    entries.sort(key=lambda e: e["name"])
    return entries


def rasterize_svg(svg_bytes: bytes, size: int = 256):
    """SVG -> Pillow-Graustufenbild (Modus "L"), size×size: QSvgRenderer rendert in eine
    transparente QImage; alle nicht-transparenten Pixel werden schwarz auf Weiß gemalt
    (Alpha des Originals als Deckkraft)."""
    from PIL import Image
    from PySide6.QtCore import QByteArray, Qt
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    renderer = QSvgRenderer(QByteArray(svg_bytes))
    image = QImage(size, size, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    try:
        renderer.render(painter)
    finally:
        painter.end()
    buf = image.bits().tobytes()
    rgba = Image.frombuffer("RGBA", (size, size), buf, "raw", "BGRA", 0, 1)
    alpha = rgba.split()[3]
    black = Image.new("RGB", (size, size), (0, 0, 0))
    white = Image.new("RGB", (size, size), (255, 255, 255))
    white.paste(black, (0, 0), alpha)
    return white.convert("L")


def _http_get(url: str, timeout: int = 30) -> bytes:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.read()


def _extract_svg_title(svg_bytes: bytes) -> str | None:
    match = re.search(rb"<title>(.*?)</title>", svg_bytes, re.DOTALL)
    if not match:
        return None
    return match.group(1).decode("utf-8").strip()


def _resolve_simple_icons_version() -> str:
    try:
        data = json.loads(_http_get(SIMPLE_ICONS_VERSIONS_URL))
    except Exception as exc:  # pragma: no cover (Netzfehler, main() meldet das)
        print(f"Simple-Icons-Versionsliste nicht erreichbar ({exc}), nutze {SIMPLE_ICONS_PREFERRED_VERSION}")
        return SIMPLE_ICONS_PREFERRED_VERSION
    versions = data.get("versions", [])
    if SIMPLE_ICONS_PREFERRED_VERSION in versions:
        return SIMPLE_ICONS_PREFERRED_VERSION
    v13 = [v for v in versions if v.startswith("13.")]
    if v13:
        return v13[0]
    return SIMPLE_ICONS_PREFERRED_VERSION


def fetch_tabler(force: bool = False) -> bool:
    """Liefert True, wenn Tabler-Assets nach dem Aufruf vollständig vorhanden sind."""
    TARGET.mkdir(parents=True, exist_ok=True)
    ttf_path = TARGET / "tabler-icons.ttf"
    index_path = TARGET / "tabler-index.json"
    license_path = TARGET / "LICENSE-tabler.txt"
    if not force and ttf_path.exists() and index_path.exists() and license_path.exists():
        print("Tabler Icons bereits vorhanden")
        return True
    print(f"Lade Tabler Icons {TABLER_VERSION} …")
    try:
        ttf_bytes = _http_get(TABLER_TTF_URL, timeout=60)
        icons_json = json.loads(_http_get(TABLER_JSON_URL, timeout=60))
        license_bytes = _http_get(TABLER_LICENSE_URL)
    except Exception as exc:
        print(f"Tabler Icons: Download fehlgeschlagen ({exc})")
        return ttf_path.exists() and index_path.exists() and license_path.exists()
    ttf_path.write_bytes(ttf_bytes)
    index = {"version": TABLER_VERSION, "icons": build_tabler_index(icons_json)}
    index_path.write_text(json.dumps(index, separators=(",", ":")), encoding="utf-8")
    license_path.write_bytes(license_bytes)
    print(f"Tabler Icons: {len(index['icons'])} Symbole")
    return True


def fetch_simple_icons(force: bool = False) -> bool:
    """Liefert True, wenn alle angeforderten Simple-Icons-Assets vorhanden sind."""
    SIMPLE_TARGET.mkdir(parents=True, exist_ok=True)
    init_path = SIMPLE_TARGET / "__init__.py"
    if not init_path.exists():
        init_path.write_text("", encoding="utf-8")
    index_path = SIMPLE_TARGET / "index.json"
    license_path = SIMPLE_TARGET / "LICENSE-simple-icons.txt"
    marken_path = SIMPLE_TARGET / "MARKEN.txt"
    have_all_pngs = all((SIMPLE_TARGET / f"{slug}.png").exists() for slug in SIMPLE_ICON_SLUGS)
    if not force and have_all_pngs and index_path.exists() and license_path.exists():
        print("Simple Icons bereits vorhanden")
        if not marken_path.exists():
            marken_path.write_text(MARKEN_TEXT, encoding="utf-8")
        return True

    version = _resolve_simple_icons_version()
    print(f"Lade Simple Icons {version} …")
    icons = []
    ok = True
    for slug in SIMPLE_ICON_SLUGS:
        png_path = SIMPLE_TARGET / f"{slug}.png"
        if not force and png_path.exists():
            title = slug
            existing = {e["name"]: e.get("title", e["name"]) for e in json.loads(index_path.read_text(encoding="utf-8")).get("icons", [])} if index_path.exists() else {}
            icons.append({"name": slug, "title": existing.get(slug, slug)})
            continue
        url = SIMPLE_ICON_SVG_URL.format(version=version, slug=slug)
        try:
            svg_bytes = _http_get(url)
        except Exception as exc:
            print(f"{slug}: übersprungen ({exc})")
            ok = False
            continue
        title = _extract_svg_title(svg_bytes) or slug
        image = rasterize_svg(svg_bytes, 256)
        image.save(png_path)
        icons.append({"name": slug, "title": title})
        print(f"{slug}: geladen")

    index_path.write_text(
        json.dumps({"version": version, "icons": icons}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    try:
        license_path.write_bytes(_http_get(SIMPLE_ICON_LICENSE_URL.format(version=version)))
    except Exception as exc:
        print(f"Simple-Icons-Lizenz: Download fehlgeschlagen ({exc})")
        ok = ok and license_path.exists()
    marken_path.write_text(MARKEN_TEXT, encoding="utf-8")
    return ok and all((SIMPLE_TARGET / f"{slug}.png").exists() for slug in SIMPLE_ICON_SLUGS)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="vorhandene Dateien erneut laden")
    args = parser.parse_args(argv)
    tabler_ok = fetch_tabler(args.force)
    simple_ok = fetch_simple_icons(args.force)
    return 0 if (tabler_ok and simple_ok) else 1


if __name__ == "__main__":
    raise SystemExit(main())
