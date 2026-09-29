"""Icon-Bibliothek zur Renderzeit: Tabler-Font, vorgerasterte Simple Icons, eigene PNGs.

Kein Qt hier; nur das Hol-Skript (`tools/fetch_icons.py`) nutzt PySide6/QtSvg. Paketdaten
werden ausschließlich über `importlib.resources` gelesen (funktioniert auch aus Zip/frozen).
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from tapesmith import paths
from tapesmith.i18n import N_, _t

ICON_SETS = ("tabler", "simple", "user")
USER_ICON_SIZE = 256

_TABLER_PKG = "tapesmith.icons"
_SIMPLE_PKG = "tapesmith.icons.simple"


class IconMissing(ValueError):
    pass


@dataclass(frozen=True)
class IconInfo:
    ref: str
    set: str
    name: str
    label: str
    category: str
    tags: tuple[str, ...]


def parse_ref(ref: str) -> tuple[str, str]:
    parts = ref.split(":", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise IconMissing(_t("Icon-Referenz '{ref}' ungültig (Form satz:name)", ref=ref))
    return parts[0], parts[1]


def _tabler_label(name: str) -> str:
    return " ".join(part.capitalize() for part in name.split("-") if part)


@lru_cache(maxsize=1)
def _tabler_data() -> dict:
    text = resources.files(_TABLER_PKG).joinpath("tabler-index.json").read_text(encoding="utf-8")
    return json.loads(text)


@lru_cache(maxsize=1)
def _tabler_icons() -> tuple[IconInfo, ...]:
    icons = []
    for entry in _tabler_data().get("icons", []):
        name = entry["name"]
        icons.append(
            IconInfo(
                ref=f"tabler:{name}",
                set="tabler",
                name=name,
                label=_tabler_label(name),
                category=entry.get("category") or "",
                tags=tuple(t for t in entry.get("tags", ()) if isinstance(t, str)),
            )
        )
    return tuple(icons)


@lru_cache(maxsize=1)
def _tabler_unicode_map() -> dict:
    return {entry["name"]: entry["unicode"] for entry in _tabler_data().get("icons", [])}


@lru_cache(maxsize=1)
def _tabler_font_bytes() -> bytes:
    return resources.files(_TABLER_PKG).joinpath("tabler-icons.ttf").read_bytes()


@lru_cache(maxsize=256)
def _tabler_font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(BytesIO(_tabler_font_bytes()), size)


@lru_cache(maxsize=1)
def _simple_data() -> dict:
    text = resources.files(_SIMPLE_PKG).joinpath("index.json").read_text(encoding="utf-8")
    return json.loads(text)


@lru_cache(maxsize=1)
def _simple_icons() -> tuple[IconInfo, ...]:
    icons = []
    for entry in _simple_data().get("icons", []):
        name = entry["name"]
        title = entry.get("title", name)
        icons.append(
            IconInfo(
                ref=f"simple:{name}",
                set="simple",
                name=name,
                label=title,
                category="Marken",
                tags=(title,),
            )
        )
    return tuple(icons)


@lru_cache(maxsize=64)
def _simple_png_bytes(name: str) -> bytes:
    return resources.files(_SIMPLE_PKG).joinpath(f"{name}.png").read_bytes()


def user_icon_dir() -> Path:
    path = paths.app_dir() / "icons"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _user_icons() -> list[IconInfo]:
    icons = []
    for file in sorted(user_icon_dir().glob("*.png")):
        name = file.stem
        icons.append(
            IconInfo(ref=f"user:{name}", set="user", name=name, label=name, category="Eigene", tags=())
        )
    return icons


def all_icons() -> list[IconInfo]:
    return list(_tabler_icons()) + list(_simple_icons()) + _user_icons()


@lru_cache(maxsize=1)
def _categories_data() -> dict:
    text = resources.files(_TABLER_PKG).joinpath("categories.json").read_text(encoding="utf-8")
    return json.loads(text)


# Anzeigenamen der Kategorien (die Namen selbst sind Kennungen, z. B. für `icons_in_category`).
CATEGORY_LABELS = {"Homelab": N_("Homelab"), "Stecker": N_("Stecker"), "Warnung": N_("Warnung"),
                   "Küche/Vorrat": N_("Küche/Vorrat"), "Schule": N_("Schule"), "Werkstatt": N_("Werkstatt"),
                   "Marken": N_("Marken"), "Eigene": N_("Eigene")}


def category_label(name: str) -> str:
    """Anzeigename einer Kategorie in der Sprache der Anfrage."""
    return _t(CATEGORY_LABELS[name]) if name in CATEGORY_LABELS else name


def categories() -> list[str]:
    names = [name for name in _categories_data().keys() if name != "synonyme"]
    if _user_icons() and "Eigene" not in names:
        names = names + ["Eigene"]
    return names


def _icon_lookup() -> dict:
    return {icon.ref: icon for icon in all_icons()}


def icons_in_category(name: str) -> list[IconInfo]:
    if name == "Marken":
        return list(_simple_icons())
    if name == "Eigene":
        return _user_icons()
    lookup = _icon_lookup()
    result = []
    for ref in _categories_data().get(name, []):
        icon = lookup.get(ref)
        if icon is not None:
            result.append(icon)
    return result


def search_icons(query: str, category: str | None = None, limit: int = 200) -> list[IconInfo]:
    pool = icons_in_category(category) if category is not None else all_icons()
    q = (query or "").strip().lower()
    if not q:
        return pool[:limit]

    synonyms = _categories_data().get("synonyme", {})
    synonym_refs: set = set()
    for word, refs in synonyms.items():
        w = word.lower()
        if q in w or w in q:
            synonym_refs.update(refs)

    exact, prefix, other = [], [], []
    seen: set = set()
    for icon in pool:
        if icon.ref in seen:
            continue
        haystacks = (icon.name.lower(), icon.label.lower()) + tuple(t.lower() for t in icon.tags)
        if icon.name.lower() == q:
            exact.append(icon)
            seen.add(icon.ref)
        elif any(h.startswith(q) for h in haystacks):
            prefix.append(icon)
            seen.add(icon.ref)
        elif icon.ref in synonym_refs or any(q in h for h in haystacks):
            other.append(icon)
            seen.add(icon.ref)

    return (exact + prefix + other)[:limit]


def _render_tabler(name: str, size: int) -> Image.Image:
    codepoint = _tabler_unicode_map().get(name)
    if codepoint is None:
        raise IconMissing(_t("Icon 'tabler:{name}' nicht gefunden, in der Icon-Suche auswählen", name=name))
    ch = chr(codepoint)
    fs = size
    font = _tabler_font(fs)
    bbox = font.getbbox(ch, anchor="lt")
    while fs > 1 and (bbox[2] - bbox[0] > size or bbox[3] - bbox[1] > size):
        fs -= 1
        font = _tabler_font(fs)
        bbox = font.getbbox(ch, anchor="lt")
    image = Image.new("1", (size, size), 255)
    draw = ImageDraw.Draw(image)
    draw.fontmode = "1"
    tx = (size - (bbox[2] - bbox[0])) / 2 - bbox[0]
    ty = (size - (bbox[3] - bbox[1])) / 2 - bbox[1]
    draw.text((tx, ty), ch, font=font, fill=0, anchor="lt")
    return image


def _render_bitmap(png_bytes: bytes, size: int, threshold: int) -> Image.Image:
    source = Image.open(BytesIO(png_bytes)).convert("L")
    scale = min(size / source.width, size / source.height)
    new_w = max(1, round(source.width * scale))
    new_h = max(1, round(source.height * scale))
    resized = source.resize((new_w, new_h), Image.LANCZOS)
    canvas = Image.new("L", (size, size), 255)
    canvas.paste(resized, ((size - new_w) // 2, (size - new_h) // 2))
    return canvas.point(lambda p: 0 if p < threshold else 255).convert("1")


def render_icon(ref: str, size: int, *, threshold: int = 128) -> Image.Image:
    if size < 8:
        raise ValueError(_t("Icon zu klein (mindestens 8 Punkte)"))
    icon_set, name = parse_ref(ref)
    if icon_set == "tabler":
        return _render_tabler(name, size)
    if icon_set == "simple":
        try:
            data = _simple_png_bytes(name)
        except (FileNotFoundError, OSError) as exc:
            raise IconMissing(_t("Icon '{ref}' nicht gefunden, in der Icon-Suche auswählen", ref=ref)) from exc
        return _render_bitmap(data, size, threshold)
    if icon_set == "user":
        path = user_icon_dir() / f"{name}.png"
        if not path.is_file():
            raise IconMissing(_t("Icon '{ref}' nicht gefunden, in der Icon-Suche auswählen", ref=ref))
        return _render_bitmap(path.read_bytes(), size, threshold)
    raise IconMissing(_t("Icon '{ref}' nicht gefunden, in der Icon-Suche auswählen", ref=ref))


def _slugify(name: str) -> str:
    text = name.strip().lower()
    for umlaut, plain in {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}.items():
        text = text.replace(umlaut, plain)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def _prepare_user_image(image: Image.Image) -> Image.Image:
    if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        background.paste(rgba, (0, 0), rgba)
        gray_source = background.convert("L")
    else:
        gray_source = image.convert("L")
    scale = min(USER_ICON_SIZE / gray_source.width, USER_ICON_SIZE / gray_source.height)
    new_w = max(1, round(gray_source.width * scale))
    new_h = max(1, round(gray_source.height * scale))
    resized = gray_source.resize((new_w, new_h), Image.LANCZOS)
    canvas = Image.new("L", (USER_ICON_SIZE, USER_ICON_SIZE), 255)
    canvas.paste(resized, ((USER_ICON_SIZE - new_w) // 2, (USER_ICON_SIZE - new_h) // 2))
    return canvas


def import_user_icon(image: Image.Image, name: str) -> str:
    slug = _slugify(name)
    if not slug:
        raise ValueError(_t("Name darf nicht leer sein"))
    directory = user_icon_dir()
    candidate = slug
    n = 2
    while (directory / f"{candidate}.png").exists():
        candidate = f"{slug}-{n}"
        n += 1
    prepared = _prepare_user_image(image)
    prepared.save(directory / f"{candidate}.png")
    return f"user:{candidate}"
