"""Update-Manifest: UTF-8-JSON, signiert mit Ed25519 (`signing`).

Schema 2 (aktuell, Verteilung über Python): Version, Kanal, Notizen und eine vollständige
Lock-Liste aller Pakete (`packages`: Name, Version, SHA-256 aller zugelassenen Wheels für
`win_amd64` und die unterstützten Python-Versionen, optional eine Einschränkung auf eine
Python-Version). Aus genau dieser signierten Liste erzeugt der Updater `lock.txt` für
`pip install --require-hashes --only-binary=:all:`; pip installiert damit nur Dateien, deren
Prüfsumme im signierten Manifest steht, egal von welchem Index sie kommen.

Schema 1 (früherer portabler Build: Zip mit SHA-256) wird weiter gelesen, damit eine alte
Quelle keinen Fehler auslöst; eine Python-Installation bietet solche Releases nie an
(`Manifest.kind == "portable"`).

Signiert werden genau die Bytes, die `build_manifest` erzeugt bzw. die heruntergeladen wurden;
`parse_manifest` prüft nur die Form, die Signatur prüft `signing.verify`."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from tapesmith.install.layout import parse_version
from tapesmith.update.errors import UpdateError
from tapesmith.i18n import _t

SCHEMA = 2
LEGACY_SCHEMA = 1
APP = "tapesmith"
CHANNELS = ("stable", "beta")
KIND_PYTHON = "python"
KIND_PORTABLE = "portable"
PLATFORM = "win_amd64"
LOCK_NAME = "lock.txt"

_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_NAME_RE = re.compile(r"^[a-z0-9]([a-z0-9._-]*[a-z0-9])?$")
_PKG_VERSION_RE = re.compile(r"^[0-9][A-Za-z0-9.+!_-]*$")
_PYVER_RE = re.compile(r"^3\.\d{1,2}$")
_WHEEL_RE = re.compile(r"^(?P<name>[^-]+)-(?P<version>[^-]+)(-\d[^-]*)?-(?P<py>[^-]+)-(?P<abi>[^-]+)-(?P<plat>[^-]+)\.whl$")


@dataclass(frozen=True)
class LockEntry:
    """Ein Paket der Lock-Liste. `python`: nur für diese Python-Version (sonst für alle)."""

    name: str
    version: str
    hashes: tuple[str, ...]
    python: str | None = None

    def marker(self) -> str | None:
        return f'python_version == "{self.python}"' if self.python else None


@dataclass(frozen=True)
class Manifest:
    version: str
    channel: str
    published: str
    notes: str
    kind: str = KIND_PYTHON
    python: tuple[str, ...] = ()
    platform: str = PLATFORM
    packages: tuple[LockEntry, ...] = field(default_factory=tuple)
    # Nur Schema 1 (portabler Build, Zip)
    file: str | None = None
    sha256: str | None = None
    size: int = 0


def _invalid(detail: str) -> UpdateError:
    return UpdateError("update.source_invalid", _t("Update-Manifest ungültig: {detail}", detail=detail))


def _text(data: dict, key: str, *, allow_empty: bool = False) -> str:
    value = data.get(key)
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise _invalid(_t("'{key}' fehlt oder ist kein Text", key=key))
    return value


def canonical_name(name: str) -> str:
    """Paketname nach PEP 503 (klein, `-` statt `_`/`.`)."""
    return re.sub(r"[-_.]+", "-", name).lower()


def check_file_name(name: str) -> str:
    """Reiner Dateiname (keine Pfadtrenner, kein `..`), sonst `update.source_invalid`."""
    if not name or any(sep in name for sep in ("/", "\\", ":")) or name in (".", "..") or ".." in name:
        raise _invalid(_t("Dateiname nicht erlaubt: {name!r}", name=name))
    return name


def _parse_packages(raw: object, pythons: tuple[str, ...]) -> tuple[LockEntry, ...]:
    if not isinstance(raw, list) or not raw:
        raise _invalid(_t("'packages' fehlt oder ist leer"))
    entries = []
    for item in raw:
        if not isinstance(item, dict):
            raise _invalid(_t("Eintrag in 'packages' ist kein Objekt"))
        name = item.get("name")
        version = item.get("version")
        hashes = item.get("sha256")
        python = item.get("python")
        if not isinstance(name, str) or not _NAME_RE.match(name) or canonical_name(name) != name:
            raise _invalid(_t("Paketname {name!r} ungültig", name=name))
        if not isinstance(version, str) or not _PKG_VERSION_RE.match(version):
            raise _invalid(_t("Version {version!r} von {name} ungültig", version=version, name=name))
        if not isinstance(hashes, list) or not hashes or not all(isinstance(h, str) and _SHA_RE.match(h) for h in hashes):
            raise _invalid(_t("SHA-256 von {name} fehlt oder ist ungültig", name=name))
        if python is not None and (not isinstance(python, str) or python not in pythons):
            raise _invalid(_t("Python-Version {python!r} von {name} ist nicht unterstützt", python=python, name=name))
        entries.append(LockEntry(name=name, version=version, hashes=tuple(hashes), python=python))
    return tuple(entries)


def _parse_legacy(raw: dict, version: str, channel: str, published: str, notes: str) -> Manifest:
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
    return Manifest(version=version, channel=channel, published=published, notes=notes, kind=KIND_PORTABLE,
                    file=file, sha256=sha256, size=size)


def parse_manifest(data: bytes) -> Manifest:
    try:
        raw = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise _invalid(_t("kein gültiges UTF-8-JSON")) from exc
    if not isinstance(raw, dict):
        raise _invalid(_t("kein JSON-Objekt"))
    schema = raw.get("schema")
    if schema not in (SCHEMA, LEGACY_SCHEMA) or isinstance(schema, bool):
        raise _invalid(_t("Schema {get!r} statt {schema}", get=schema, schema=SCHEMA))
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
    if schema == LEGACY_SCHEMA:
        return _parse_legacy(raw, version, channel, published, notes)

    python = raw.get("python")
    if not isinstance(python, list) or not python or not all(isinstance(p, str) and _PYVER_RE.match(p) for p in python):
        raise _invalid(_t("'python' muss eine Liste wie [\"3.11\", \"3.12\"] sein"))
    pythons = tuple(python)
    platform = _text(raw, "platform")
    if platform != PLATFORM:
        raise _invalid(_t("Plattform {platform!r} statt {expected}", platform=platform, expected=PLATFORM))
    packages = _parse_packages(raw.get("packages"), pythons)
    own = [p for p in packages if p.name == APP]
    if not own or any(p.version != version for p in own):
        raise _invalid(_t("Lock-Liste enthält {app} {version} nicht", app=APP, version=version))
    return Manifest(version=version, channel=channel, published=published, notes=notes, kind=KIND_PYTHON,
                    python=pythons, platform=platform, packages=packages)


def lock_text(manifest: Manifest) -> str:
    """`lock.txt` für `pip install --require-hashes --only-binary=:all: -r lock.txt`."""
    if manifest.kind != KIND_PYTHON:
        raise ValueError(_t("Nur Manifeste mit Lock-Liste haben eine lock.txt"))
    lines = [f"# Tapesmith {manifest.version} ({manifest.channel}), {PLATFORM}, Python {', '.join(manifest.python)}",
             "# python -m pip install --require-hashes --only-binary=:all: -r lock.txt"]
    for entry in manifest.packages:
        req = f"{entry.name}=={entry.version}"
        marker = entry.marker()
        if marker:
            req += f" ; {marker}"
        hashes = " \\\n".join(f"    --hash=sha256:{h}" for h in entry.hashes)
        lines.append(f"{req} \\\n{hashes}")
    return "\n".join(lines) + "\n"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _now_z() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# ---------- Lock-Liste aus Wheel-Ordnern (Release) ----------

def parse_wheel_name(filename: str) -> tuple[str, str, str]:
    """(kanonischer Name, Version, Plattform-Tag) aus einem Wheel-Dateinamen."""
    match = _WHEEL_RE.match(filename)
    if not match:
        raise ValueError(_t("Kein Wheel-Dateiname: {name}", name=filename))
    return canonical_name(match.group("name")), match.group("version"), match.group("plat")


def _allowed_platform(plat: str) -> bool:
    return any(p in ("any", PLATFORM) for p in plat.split("."))


def entries_from_wheels(dirs: Mapping[str, Path]) -> list[LockEntry]:
    """Lock-Einträge aus je einem Ordner mit den Wheels pro Python-Version (`pip download`):
    gleiche Version in allen Ordnern ergibt einen Eintrag mit allen Prüfsummen, sonst je
    Python-Version einen Eintrag mit Einschränkung. Nur Wheels für `win_amd64` oder `any`."""
    per_python: dict[str, dict[str, tuple[str, set[str]]]] = {}
    for py, folder in dirs.items():
        if not _PYVER_RE.match(py):
            raise ValueError(_t("Python-Version {py!r} ungültig", py=py))
        found: dict[str, tuple[str, set[str]]] = {}
        wheels = sorted(Path(folder).glob("*.whl"))
        if not wheels:
            raise ValueError(_t("Keine Wheels in {folder}", folder=folder))
        for wheel in wheels:
            name, version, plat = parse_wheel_name(wheel.name)
            if not _allowed_platform(plat):
                raise ValueError(_t("Wheel {name} passt nicht zu {platform}", name=wheel.name, platform=PLATFORM))
            if name in found and found[name][0] != version:
                raise ValueError(_t("{name} liegt in {folder} in zwei Versionen vor", name=name, folder=folder))
            found.setdefault(name, (version, set()))[1].add(file_sha256(wheel))
        per_python[py] = found
    pythons = sorted(per_python, key=lambda v: tuple(int(x) for x in v.split(".")))
    names = sorted({n for found in per_python.values() for n in found})
    entries: list[LockEntry] = []
    for name in names:
        present = {py: per_python[py][name] for py in pythons if name in per_python[py]}
        versions = {v for v, _h in present.values()}
        if len(present) == len(pythons) and len(versions) == 1:
            hashes = sorted(set().union(*(h for _v, h in present.values())))
            entries.append(LockEntry(name=name, version=versions.pop(), hashes=tuple(hashes)))
        else:
            for py, (version, hashes) in present.items():
                entries.append(LockEntry(name=name, version=version, hashes=tuple(sorted(hashes)), python=py))
    return entries


def build_manifest(version: str, notes: str, packages: Iterable[LockEntry], *, python: Iterable[str],
                   channel: str = "stable", published: str | None = None) -> bytes:
    """Kanonische Manifest-Bytes (Schema 2, sortierte Schlüssel, Einzug 2, Zeilenende)."""
    parse_version(version)
    if channel not in CHANNELS:
        raise ValueError(_t("Kanal {channel!r} unbekannt (erlaubt: {items})", channel=channel, items=', '.join(CHANNELS)))
    pythons = sorted(set(python), key=lambda v: tuple(int(x) for x in v.split(".")))
    data = {
        "schema": SCHEMA,
        "app": APP,
        "version": version,
        "channel": channel,
        "published": published or _now_z(),
        "notes": notes,
        "platform": PLATFORM,
        "python": pythons,
        "packages": [
            {"name": p.name, "version": p.version, "sha256": list(p.hashes),
             **({"python": p.python} if p.python else {})}
            for p in sorted(packages, key=lambda e: (e.name, e.python or ""))
        ],
    }
    raw = (json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    parse_manifest(raw)  # dieselbe Prüfung wie beim Updater, bevor signiert wird
    return raw
