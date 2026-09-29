"""Vorlagengalerie: Suche, Gruppierung, Favoriten/Verlauf, Paket-Im-/Export, Wickel-Markierung.

Ohne Qt: die GUI-Seite (`gui/gallery_page.py`) baut Kacheln daraus. Zähler werden hier nie
verändert: alle Funktionen greifen nur lesend (`CounterStore.peek`) zu.
"""

from __future__ import annotations

import json
import zipfile
from collections.abc import Callable, Sequence
from pathlib import Path

from PIL import Image, ImageDraw

from tapesmith import config
from tapesmith.history import HistoryStore
from tapesmith.render.icons import user_icon_dir
from tapesmith.templates.model import Template, template_from_dict, template_source_dict, template_to_dict
from tapesmith.i18n import N_, _t

FAVORITES = N_("Favoriten")
RECENT = N_("Zuletzt verwendet")
ALL = N_("Alle")

MANIFEST_FORMAT = "tapesmith-paket"
# Pakete aus der Zeit vor Tapesmith 0.3 (App-Name "P12 Label") lassen sich weiter importieren.
LEGACY_MANIFEST_FORMAT = "p12label-paket"
MANIFEST_VERSION = 1

WRAP_COLOR = (70, 130, 220)      # Wickelbereich
OVERLAP_COLOR = (230, 150, 40)   # Überlappung


def _haystack(t: Template) -> str:
    parts = [t.name, t.title, t.description, t.category, *t.tags]
    for f in t.fields:
        parts.append(f.id)
        parts.append(f.label)
    return " ".join(parts).lower()


def search_templates(templates: Sequence[Template], query: str) -> list[Template]:
    """Case-insensitiv in Name, Beschreibung, Kategorie, Tags, Feld-IDs und -Anzeigenamen;
    alle Wörter der Suche müssen (irgendwo) treffen."""
    words = query.lower().split()
    if not words:
        return list(templates)
    result = []
    for t in templates:
        hay = _haystack(t)
        if all(w in hay for w in words):
            result.append(t)
    return result


def group_by_category(templates: Sequence[Template]) -> dict[str, list[Template]]:
    """Leere Kategorie -> "Allgemein", Kategorien alphabetisch, Vorlagen je Kategorie nach Name."""
    groups: dict[str, list[Template]] = {}
    for t in templates:
        groups.setdefault(t.category or _t("Allgemein"), []).append(t)
    return {cat: sorted(items, key=lambda t: t.name) for cat, items in sorted(groups.items())}


def recent_template_names(history: HistoryStore, n: int = 8, scan_limit: int = 300) -> list[str]:
    """Neueste zuerst, eindeutig, nur Einträge mit Vorlage und Status "ok"."""
    entries = history.search("", limit=scan_limit)
    names: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        if entry.status != "ok" or not entry.template:
            continue
        if entry.template in seen:
            continue
        seen.add(entry.template)
        names.append(entry.template)
        if len(names) >= n:
            break
    return names


def favorites(cfg: dict) -> list[str]:
    return list(config.gui_setting(cfg, "favorites"))


def toggle_favorite(cfg: dict, name: str, save: Callable[[dict], dict]) -> list[str]:
    """Anpinnen/lösen: neue Liste über `save({"gui": {...}})` speichern, `cfg` aktualisieren."""
    favs = list(favorites(cfg))
    if name in favs:
        favs.remove(name)
    else:
        favs.append(name)
    gui = dict(cfg.get("gui", {}))
    gui["favorites"] = favs
    save({"gui": gui})
    cfg["gui"] = gui
    return favs


def sample_values(template: Template) -> dict[str, str]:
    """Werte für die Eingabefelder: `default`, überschrieben von `sample`."""
    values: dict[str, str] = {}
    for f in template.fields:
        if f.type == "input":
            values[f.id] = template.sample.get(f.id, f.default)
    return values


def _used_user_icons(templates: Sequence[Template]) -> set[str]:
    used: set[str] = set()
    for t in templates:
        if t.document is None:
            continue
        for obj in t.document.objects:
            if obj.kind == "icon" and obj.icon.startswith("user:"):
                used.add(obj.icon.split(":", 1)[1])
    return used


def export_package(templates: Sequence[Template], path: Path, *, include_user_icons: bool = True) -> Path:
    path = Path(path)
    manifest = {
        "format": MANIFEST_FORMAT, "version": MANIFEST_VERSION,
        "templates": [t.name for t in templates],
    }
    icon_names = _used_user_icons(templates) if include_user_icons else set()
    with zipfile.ZipFile(path, "w") as zf:
        for t in templates:
            # übersetzt geladene Vorlagen in der Form der Datei (Basis plus Übersetzungsblock)
            data = template_source_dict(t) if t.localized else template_to_dict(t)
            zf.writestr(f"{t.name}.tapesmith.json", json.dumps(data, ensure_ascii=False, indent=2))
        icon_dir = user_icon_dir()
        for name in sorted(icon_names):
            icon_path = icon_dir / f"{name}.png"
            if icon_path.is_file():
                zf.writestr(f"icons/{name}.png", icon_path.read_bytes())
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    return path


def _check_zip_paths(names: Sequence[str]) -> None:
    for n in names:
        normalized = n.replace("\\", "/")
        if normalized.startswith("/") or ":" in normalized or ".." in Path(normalized).parts:
            raise ValueError(_t("Paket enthält unzulässigen Pfad: {n}", n=n))


def import_package(path: Path, target_dir: Path, *, overwrite: bool = False) -> list[str]:
    """Prüft `manifest.json` und validiert jede Vorlage per `template_from_dict`, bevor
    irgendetwas geschrieben wird. Namenskonflikt (ohne `overwrite`) -> Zusatz "-2", "-3"."""
    path = Path(path)
    target_dir = Path(target_dir)
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        _check_zip_paths(names)

        try:
            manifest_raw = zf.read("manifest.json")
        except KeyError as exc:
            raise ValueError(_t("Paket enthält kein manifest.json")) from exc
        try:
            manifest = json.loads(manifest_raw)
        except json.JSONDecodeError as exc:
            raise ValueError(_t("Paket: manifest.json ist kein gültiges JSON")) from exc
        if manifest.get("format") not in (MANIFEST_FORMAT, LEGACY_MANIFEST_FORMAT):
            raise ValueError(_t("Paket: unbekanntes Format"))

        template_names = manifest.get("templates", [])
        parsed: list[tuple[dict, Template]] = []
        for tname in template_names:
            entry_name = f"{tname}.tapesmith.json"
            legacy_name = f"{tname}.p12label.json"
            if entry_name not in names and legacy_name in names:
                entry_name = legacy_name
            try:
                raw = zf.read(entry_name)
            except KeyError as exc:
                raise ValueError(_t("Paket: Vorlage '{tname}' fehlt ({entry_name})", tname=tname, entry_name=entry_name)) from exc
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(_t("Paket: Vorlage '{tname}' ist kein gültiges JSON", tname=tname)) from exc
            template = template_from_dict(data)  # wirft TemplateError (ValueError) bei Ungültigem
            parsed.append((data, template))

        icon_bytes: dict[str, bytes] = {}
        for n in names:
            if n.startswith("icons/") and n.endswith(".png"):
                icon_bytes[n[len("icons/"):]] = zf.read(n)

        # Alles validiert, erst jetzt schreiben.
        target_dir.mkdir(parents=True, exist_ok=True)
        imported: list[str] = []
        for data, template in parsed:
            final_name = template.name
            dest = target_dir / f"{final_name}.tapesmith.json"
            if dest.exists() and not overwrite:
                n = 2
                while (target_dir / f"{template.name}-{n}.tapesmith.json").exists():
                    n += 1
                final_name = f"{template.name}-{n}"
                dest = target_dir / f"{final_name}.tapesmith.json"
                data = dict(data)
                data["name"] = final_name
            dest.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            imported.append(final_name)

        icon_dir = user_icon_dir()
        for name, raw in icon_bytes.items():
            dest_icon = icon_dir / f"{name}.png"
            if not dest_icon.exists():
                dest_icon.write_bytes(raw)

    return imported


def wrap_marks_image(landscape: Image.Image, extra: dict, *, bar: int = 10) -> Image.Image:
    """Streifenbild unter der Kabelwickel-Vorschau: Label oben, darunter ein Balken mit
    Wickelbereich/Überlappung; zusätzlich eine 1-Pixel-Linie am Beginn der Überlappung im Label."""
    wrap_rows = int(extra.get("wrap_rows", 0))
    overlap_rows = int(extra.get("overlap_rows", 0))
    width = landscape.width
    height = landscape.height + bar

    label_rgb = landscape.convert("RGB")
    if 0 <= wrap_rows < width:
        draw = ImageDraw.Draw(label_rgb)
        draw.line((wrap_rows, 0, wrap_rows, landscape.height - 1), fill=OVERLAP_COLOR)

    image = Image.new("RGB", (width, height), (255, 255, 255))
    image.paste(label_rgb, (0, 0))

    wrap_end = max(0, min(width, wrap_rows))
    overlap_end = max(wrap_end, min(width, wrap_rows + overlap_rows))
    if wrap_end > 0:
        image.paste(WRAP_COLOR, (0, landscape.height, wrap_end, height))
    if overlap_end > wrap_end:
        image.paste(OVERLAP_COLOR, (wrap_end, landscape.height, overlap_end, height))
    return image
