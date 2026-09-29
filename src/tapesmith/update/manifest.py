"""Update-Manifest: UTF-8-JSON mit Version, Kanal, Notizen und Paket (Datei, SHA-256, Größe).

Signiert werden genau die Bytes, die `build_manifest` erzeugt bzw. die heruntergeladen wurden;
`parse_manifest` prüft nur die Form, die Signatur prüft `signing.verify`."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from tapesmith.install.layout import parse_version
from tapesmith.update.errors import UpdateError
from tapesmith.i18n import _t

SCHEMA = 1
APP = "tapesmith"
CHANNELS = ("stable", "beta")

_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class Manifest:
    version: str
    channel: str
    published: str
    notes: str
    file: str
    sha256: str
    size: int


def _invalid(detail: str) -> UpdateError:
    return UpdateError("update.source_invalid", _t("Update-Manifest ungültig: {detail}", detail=detail))


def _text(data: dict, key: str, *, allow_empty: bool = False) -> str:
    value = data.get(key)
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise _invalid(_t("'{key}' fehlt oder ist kein Text", key=key))
    return value


def check_file_name(name: str) -> str:
    """Reiner Dateiname (keine Pfadtrenner, kein `..`), sonst `update.source_invalid`."""
    if not name or any(sep in name for sep in ("/", "\\", ":")) or name in (".", "..") or ".." in name:
        raise _invalid(_t("Dateiname nicht erlaubt: {name!r}", name=name))
    return name


def parse_manifest(data: bytes) -> Manifest:
    try:
        raw = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise _invalid(_t("kein gültiges UTF-8-JSON")) from exc
    if not isinstance(raw, dict):
        raise _invalid(_t("kein JSON-Objekt"))
    if raw.get("schema") != SCHEMA:
        raise _invalid(_t("Schema {get!r} statt {schema}", get=raw.get('schema'), schema=SCHEMA))
    if raw.get("app") != APP:
        raise _invalid(_t("falsche App {get!r}", get=raw.get('app')))
    version = _text(raw, "version")
    try:
        parse_version(version)
    except ValueError as exc:
        raise _invalid(_t("Version {version!r} ungültig", version=version)) from exc
    channel = _text(raw, "channel")
    if channel not in CHANNELS:
        raise _invalid(_t("Kanal {channel!r} unbekannt", channel=channel))
    published = _text(raw, "published")
    notes = _text(raw, "notes", allow_empty=True)
    package = raw.get("package")
    if not isinstance(package, dict):
        raise _invalid(_t("'package' fehlt"))
    file = check_file_name(_text(package, "file"))
    sha256 = _text(package, "sha256")
    if not _SHA_RE.match(sha256):
        raise _invalid(_t("'package.sha256' muss 64 Hex-Zeichen (klein) haben"))
    size = package.get("size")
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        raise _invalid(_t("'package.size' muss eine positive ganze Zahl sein"))
    return Manifest(version=version, channel=channel, published=published, notes=notes, file=file,
                    sha256=sha256, size=size)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _now_z() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_manifest(zip_path: Path, version: str, notes: str, channel: str = "stable",
                   published: str | None = None) -> bytes:
    """Kanonische Manifest-Bytes für `zip_path` (sortierte Schlüssel, Einzug 2, Zeilenende)."""
    zip_path = Path(zip_path)
    parse_version(version)
    if channel not in CHANNELS:
        raise ValueError(_t("Kanal {channel!r} unbekannt (erlaubt: {items})", channel=channel, items=', '.join(CHANNELS)))
    data = {
        "schema": SCHEMA,
        "app": APP,
        "version": version,
        "channel": channel,
        "published": published or _now_z(),
        "notes": notes,
        "package": {"file": check_file_name(zip_path.name), "sha256": file_sha256(zip_path),
                    "size": zip_path.stat().st_size},
    }
    return (json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
