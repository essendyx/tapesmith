"""Konfiguration als Code: Einstellungen, Kalibrierung, eigene Bänder/Zielobjekte,
Spaltenzuordnungen und eigene Vorlagen als lesbaren, Git-tauglichen Ordner exportieren und
wieder importieren (mit Prüfung, Trockenlauf und Sicherung des alten Stands). Secrets werden
nie im Klartext exportiert, nur als Verweis (`keyring:…`) oder mit `--strip-secrets` weggelassen.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath

from tapesmith import __version__, config, fileutil, paths
from tapesmith.device.profile import load_profile
from tapesmith.document import targets as targets_mod
from tapesmith.tape import profiles as tape_mod
from tapesmith.templates import store as template_store
from tapesmith.templates.model import template_from_dict
from tapesmith.i18n import _t

FORMAT = "tapesmith-config"
FORMAT_VERSION = 1

# Reihenfolge = Reihenfolge im Export (config.json wird gesondert behandelt, s. u.).
_SIMPLE_FILES = ("calibration.json", "tapes.json", "targets.json", "mappings.json")


@dataclass(frozen=True)
class ImportChange:
    path: str
    kind: str  # "neu" | "geändert" | "gleich"


@dataclass(frozen=True)
class ImportPlan:
    changes: tuple[ImportChange, ...]
    warnings: tuple[str, ...]
    backup_dir: Path | None


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _source_path(rel: str) -> Path:
    """Pfad der aktuellen Benutzerdatei (unter `paths.app_dir()`) für `rel`."""
    if rel == "config.json":
        return paths.config_path()
    if rel == "calibration.json":
        return paths.calibration_path()
    if rel == "tapes.json":
        return tape_mod.user_tapes_path()
    if rel == "targets.json":
        return targets_mod.user_targets_path()
    if rel == "mappings.json":
        return paths.app_dir() / "mappings.json"
    raise ValueError(_t("Unbekannte Datei: {rel}", rel=rel))


def _strip_secret_keys(cfg: dict, secret_paths: list[str]) -> dict:
    result = json.loads(json.dumps(cfg))
    for dotted in secret_paths:
        parts = dotted.split(".")
        node = result
        for part in parts[:-1]:
            node = node[part]
        node.pop(parts[-1], None)
    return result


def export_config(target: Path, *, include_templates: bool = True, strip_secrets: bool = False) -> list[Path]:
    """Exportiert die Konfiguration als lesbaren Ordner (Git-tauglich, sortierte Schlüssel)."""
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    files: dict[str, str] = {}

    config_path = paths.config_path()
    if config_path.exists():
        cfg_raw = json.loads(config_path.read_text(encoding="utf-8"))
        secrets = config.secret_keys(cfg_raw)
        if secrets:
            if not strip_secrets:
                raise ValueError(
                    _t("config.json enthält Secrets: ") + ", ".join(secrets)
                    + _t(". Als keyring:… ablegen oder --strip-secrets"))
            cfg_raw = _strip_secret_keys(cfg_raw, secrets)
        text = json.dumps(cfg_raw, indent=2, ensure_ascii=False, sort_keys=True)
        out = target / "config.json"
        out.write_text(text, encoding="utf-8")
        written.append(out)
        files["config.json"] = _sha256_bytes(text.encode("utf-8"))

    for rel in _SIMPLE_FILES:
        src = _source_path(rel)
        if not src.exists():
            continue
        data = src.read_bytes()
        out = target / rel
        out.write_bytes(data)
        written.append(out)
        files[rel] = _sha256_bytes(data)

    if include_templates:
        for file in template_store.user_template_files(template_store.user_dir()):
            data = file.read_bytes()
            tdir = target / "templates"
            tdir.mkdir(parents=True, exist_ok=True)
            out = tdir / file.name
            out.write_bytes(data)
            written.append(out)
            files[f"templates/{file.name}"] = _sha256_bytes(data)

    manifest = {
        "format": FORMAT,
        "version": FORMAT_VERSION,
        "app_version": __version__,
        "created": datetime.now().isoformat(timespec="seconds"),
        "files": files,
    }
    manifest_path = target / "MANIFEST.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    written.append(manifest_path)
    return written


_ALLOWED_TOP_LEVEL = frozenset({"config.json", *_SIMPLE_FILES})


def _check_safe_rel(rel: str) -> None:
    """Weist einen `rel`-Pfad aus dem (potenziell von Dritten bearbeiteten) `MANIFEST.json`
    zurück, wenn er außerhalb des Vorlagenordners bzw. der bekannten Top-Level-Dateien landen
    könnte. `MANIFEST.json` stammt aus einem geteilten Git-Ordner; ein präparierter
    Eintrag wie "templates/../../evil.tapesmith.json" darf NICHT bis zu `_dest_for` durchreichen,
    da `Path.__truediv__` mit '..'-Segmenten oder einem absoluten rechten Operanden (z. B.
    Laufwerksbuchstabe) den Zielordner verlassen bzw. komplett verwerfen kann. Nur bekannte
    Top-Level-Dateinamen oder "templates/<einfacher-dateiname>" ohne weitere Trennzeichen und
    ohne '..' sind erlaubt; Backslash-Namen (Windows-Trennzeichen) werden ebenfalls abgewiesen.
    """
    if "\\" in rel:
        raise ValueError(_t("{rel}: unsicherer Pfad", rel=rel))
    if rel in _ALLOWED_TOP_LEVEL:
        return
    if rel.startswith("templates/"):
        sub = rel.split("/", 1)[1]
        pure = PurePosixPath(rel)
        if not sub or "/" in sub or ".." in pure.parts or pure.is_absolute():
            raise ValueError(_t("{rel}: unsicherer Pfad", rel=rel))
        return
    raise ValueError(_t("{rel}: unbekannte Datei im Export", rel=rel))


def _dest_for(rel: str) -> Path:
    if rel.startswith("templates/"):
        return template_store.user_dir() / rel.split("/", 1)[1]
    return _source_path(rel)


def _validate_file(rel: str, path: Path) -> None:
    """Prüft eine einzelne Datei des Quellordners, bevor irgendetwas geschrieben wird."""
    if rel == "config.json":
        data = json.loads(path.read_text(encoding="utf-8"))
        secrets = config.secret_keys(data)
        if secrets:
            raise ValueError(_t("enthält Secrets: ") + ", ".join(secrets))
        config.validate_config({**config.DEFAULTS, **data})
    elif rel == "calibration.json":
        load_profile(calibration_path=path)
    elif rel == "tapes.json":
        tape_mod._load_tapes(path.read_text(encoding="utf-8"), rel)
    elif rel == "targets.json":
        targets_mod._load_targets(path.read_text(encoding="utf-8"), rel)
    elif rel == "mappings.json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(_t("mappings.json muss ein Objekt sein"))
    elif rel.startswith("templates/") and template_store.is_template_file(rel):
        data = json.loads(path.read_text(encoding="utf-8"))
        template_from_dict(data, path=None)
    else:
        raise ValueError(_t("unbekannte Datei im Export: {rel}", rel=rel))


def import_config(source: Path, *, dry_run: bool = False, include_templates: bool = True) -> ImportPlan:
    """Prüft und (außer bei `dry_run`) übernimmt den exportierten Ordner `source`.

    Jede Datei wird vor dem Schreiben geprüft; ein Fehler nennt die Datei und schreibt nichts.
    Eine Prüfsummen-Abweichung gegenüber `MANIFEST.json` ist nur eine Warnung (Dateien dürfen im
    Repo bearbeitet werden).
    """
    source = Path(source)
    manifest_path = source / "MANIFEST.json"
    if not manifest_path.exists():
        raise ValueError(_t("{source}: MANIFEST.json fehlt", source=source))
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(_t("MANIFEST.json: nicht lesbar ({exc})", exc=exc)) from exc
    if manifest.get("format") != FORMAT:
        raise ValueError(_t("MANIFEST.json: unbekanntes Format {get!r}", get=manifest.get('format')))
    version = manifest.get("version")
    if not isinstance(version, int) or version > FORMAT_VERSION:
        raise ValueError(_t("MANIFEST.json: Version {version!r} wird nicht unterstützt", version=version))

    files: dict[str, str] = manifest.get("files", {})
    entries: list[ImportChange] = []
    warnings: list[str] = []
    plan_items: list[tuple[str, Path, bytes]] = []

    for rel in sorted(files):
        if rel.startswith("templates/") and not include_templates:
            continue
        _check_safe_rel(rel)
        src_path = source / rel
        if not src_path.exists():
            raise ValueError(_t("{rel}: im Quellordner nicht gefunden", rel=rel))
        data = src_path.read_bytes()
        if _sha256_bytes(data) != files[rel]:
            warnings.append(_t("{rel}: seit dem Export geändert (Prüfsumme)", rel=rel))
        try:
            _validate_file(rel, src_path)
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            raise ValueError(f"{rel}: {exc}") from exc

        dest_path = _dest_for(rel)
        if dest_path.exists() and dest_path.read_bytes() == data:
            kind = "gleich"
        elif dest_path.exists():
            kind = "geändert"
        else:
            kind = "neu"
        entries.append(ImportChange(path=rel, kind=kind))
        plan_items.append((rel, dest_path, data))

    if dry_run:
        return ImportPlan(changes=tuple(entries), warnings=tuple(warnings), backup_dir=None)

    backup_dir = paths.app_dir() / "backups" / f"vor-import-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    for (rel, dest_path, data), entry in zip(plan_items, entries):
        if entry.kind == "gleich":
            continue
        if entry.kind == "geändert" and dest_path.exists():
            backup_target = backup_dir / rel
            backup_target.parent.mkdir(parents=True, exist_ok=True)
            backup_target.write_bytes(dest_path.read_bytes())
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        fileutil.atomic_write_bytes(dest_path, data)

    return ImportPlan(changes=tuple(entries), warnings=tuple(warnings), backup_dir=backup_dir)
