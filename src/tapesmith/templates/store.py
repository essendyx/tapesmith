"""Wo Vorlagen liegen: mitgeliefert im Paket und benutzereigen unter %APPDATA%\\Tapesmith\\templates."""

import json
import sys
from importlib import resources
from pathlib import Path

from tapesmith import config, paths
from tapesmith.templates.model import SCHEMA_VERSION, Template, TemplateError, TemplateNotFound, load_template, template_from_dict
from tapesmith.i18n import _t

SUFFIX = ".tapesmith.json"
# Endung aus der Zeit vor Tapesmith 0.3 (App-Name "P12 Label"): wird weiter gelesen, neue Dateien
# bekommen immer `SUFFIX`. Gibt es beide Dateien zu einem Namen, gewinnt die neue.
LEGACY_SUFFIX = ".p12label.json"
SUFFIXES = (SUFFIX, LEGACY_SUFFIX)


def is_template_file(name: str) -> bool:
    return name.endswith(SUFFIXES)


def strip_suffix(name: str) -> str:
    for suffix in SUFFIXES:
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def user_template_files(directory: Path) -> list[Path]:
    """Vorlagendateien eines Ordners, alte Endung vor neuer (spätere Einträge gewinnen)."""
    return sorted(directory.glob(f"*{LEGACY_SUFFIX}")) + sorted(directory.glob(f"*{SUFFIX}"))


def builtin_dir() -> Path:
    """Pfad der mitgelieferten Vorlagen im Paket, nur im Quellbaum verlässlich (Entwicklung/Tests);
    in Zip-/frozen-Builds liest `builtin_templates` stattdessen über das Traversable."""
    return Path(str(resources.files("tapesmith.templates.builtin")))


def user_dir() -> Path:
    """Vorlagenordner: `config.json`-Schlüssel `templates_dir`, falls gesetzt und die
    Konfiguration lesbar ist, sonst der Standardordner unter `paths.app_dir()`."""
    custom = None
    try:
        custom = config.load_config().get("templates_dir")
    except (ValueError, OSError, json.JSONDecodeError):
        custom = None
    path = Path(custom) if custom else paths.app_dir() / "templates"
    path.mkdir(parents=True, exist_ok=True)
    return path


def builtin_templates() -> list[Template]:
    templates: list[Template] = []
    for entry in resources.files("tapesmith.templates.builtin").iterdir():
        if not entry.name.endswith(SUFFIX):
            continue
        try:
            data = json.loads(entry.read_text(encoding="utf-8"))
            version = data.get("schema_version")
            if isinstance(version, int) and version < SCHEMA_VERSION:
                raise TemplateError(
                    _t("Vorlage {name}: Schema-Version {version} ist älter als {schema_version}, mitgelieferte Vorlagen werden nicht migriert", name=entry.name, version=version, schema_version=SCHEMA_VERSION)
                )
            template = template_from_dict(data, path=None)
        except (TemplateError, OSError, json.JSONDecodeError) as exc:
            print(_t("Warnung: Vorlage {name} übersprungen: {exc}", name=entry.name, exc=exc), file=sys.stderr)
            continue
        templates.append(template)
    return sorted(templates, key=lambda t: t.name)


def list_templates() -> list[Template]:
    found: dict[str, Template] = {}
    for template in builtin_templates():
        found[template.name] = template
    for file in user_template_files(user_dir()):
        try:
            template = load_template(file)
        except TemplateError as exc:
            print(_t("Warnung: Vorlage {name} übersprungen: {exc}", name=file.name, exc=exc), file=sys.stderr)
            continue
        found[template.name] = template
    return sorted(found.values(), key=lambda t: t.name)


def templates_by_category() -> dict[str, list[Template]]:
    """Alle Vorlagen (mitgeliefert + benutzereigen) nach Kategorie gruppiert: leere
    Kategorie -> "Allgemein", Kategorien alphabetisch, Vorlagen je Kategorie nach Name."""
    groups: dict[str, list[Template]] = {}
    for t in list_templates():
        groups.setdefault(t.category or _t("Allgemein"), []).append(t)
    return {cat: sorted(items, key=lambda t: t.name) for cat, items in sorted(groups.items())}


def find_template(name_or_path: str) -> Template:
    candidate = Path(name_or_path)
    if is_template_file(candidate.name) and candidate.is_file():
        return load_template(candidate)
    for suffix in SUFFIXES:
        file = user_dir() / f"{name_or_path}{suffix}"
        if file.is_file():
            return load_template(file)
    entry = resources.files("tapesmith.templates.builtin").joinpath(f"{name_or_path}{SUFFIX}")
    if entry.is_file():
        data = json.loads(entry.read_text(encoding="utf-8"))
        return template_from_dict(data, path=None)
    names = ", ".join(t.name for t in list_templates())
    raise TemplateNotFound(_t("Vorlage '{name_or_path}' nicht gefunden (vorhanden: {names})", name_or_path=name_or_path, names=names))
