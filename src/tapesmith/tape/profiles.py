"""Bandprofile: manuelle Bandauswahl (kein Chip, keine Erkennung).

Jedes Band trägt Band-/Druckfarbe für die Vorschau, das Material, ob es transparent
ist (Vorschau als Schachbrett, siehe `tape.preview`) und optional einen festen
`code_mode` für die Codes; leer bedeutet automatisch: „invert" bei dunklem
Band, sonst „normal". `density` ist ein rein experimentelles Feld und wird nie
an den Drucker gesendet. `translations.<sprache>.name` übersetzt den Anzeigenamen.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from tapesmith import config, fileutil, i18n, paths
from tapesmith.i18n import _t

MATERIALS = ("kunststoff", "papier", "textil")
CODE_MODES = ("normal", "invert", "warn")
DEFAULT_TAPE = "schwarz-weiss"
DENSITY_FAMILIES = ("m110", "m02")

RGB = tuple[int, int, int]


def _luminance(rgb: RGB) -> float:
    r, g, b = rgb
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


@dataclass(frozen=True)
class TapeProfile:
    id: str
    name: str
    background: RGB
    ink: RGB
    material: str = "kunststoff"
    transparent: bool = False
    code_mode: str = ""                 # "" -> automatisch (siehe effective_code_mode)
    density: int | None = None          # experimentell, wird nie gesendet
    density_family: str | None = None   # "m110"/"m02"; experimentell, wird nie gesendet

    @property
    def dark(self) -> bool:
        """Relative Luminanz des Bandes < Luminanz der Druckfarbe (dunkles Band)."""
        return _luminance(self.background) < _luminance(self.ink)

    @property
    def effective_code_mode(self) -> str:
        if self.code_mode:
            return self.code_mode
        return "invert" if self.dark else "normal"


def _check_color(value, field: str, hint) -> RGB:
    ok = (isinstance(value, (list, tuple)) and len(value) == 3
          and all(isinstance(c, int) and not isinstance(c, bool) and 0 <= c <= 255 for c in value))
    if not ok:
        raise ValueError(_t("{hint}: '{field}' muss eine Farbe [r, g, b] (0..255) sein, ist {value!r}", hint=hint, field=field, value=value))
    return (int(value[0]), int(value[1]), int(value[2]))


def _parse_tape(raw: dict, hint) -> TapeProfile:
    try:
        tape_id = raw["id"]
        name = raw["name"]
        background = _check_color(raw["background"], "background", hint)
        ink = _check_color(raw["ink"], "ink", hint)
    except KeyError as exc:
        raise ValueError(_t("{hint}: Bandprofil unvollständig, Schlüssel fehlt: {exc}", hint=hint, exc=exc)) from exc

    material = raw.get("material", "kunststoff")
    if material not in MATERIALS:
        raise ValueError(_t("{hint}: 'material' muss eines von {materials} sein, ist {material!r}", hint=hint, materials=MATERIALS, material=material))

    transparent = bool(raw.get("transparent", False))

    code_mode = raw.get("code_mode", "")
    if code_mode not in ("",) + CODE_MODES:
        raise ValueError(_t("{hint}: 'code_mode' muss eines von {code_modes} oder '' sein, ist {code_mode!r}", hint=hint, code_modes=CODE_MODES, code_mode=code_mode))

    density = raw.get("density")
    if density is not None:
        ok = isinstance(density, int) and not isinstance(density, bool) and 1 <= density <= 15
        if not ok:
            raise ValueError(_t("{hint}: 'density' muss None oder 1..15 sein, ist {density!r}", hint=hint, density=density))

    translations = raw.get("translations") or {}
    if not isinstance(translations, dict) or not all(
            isinstance(block, dict) and isinstance(block.get("name", ""), str) for block in translations.values()):
        raise ValueError(_t("{hint}: 'translations' muss je Sprache ein Objekt mit dem Text 'name' sein", hint=hint))
    # Anzeigename in der Sprache der Anfrage (`translations.<sprache>.name`), die id bleibt.
    name = (translations.get(i18n.language()) or {}).get("name") or name

    density_family = raw.get("density_family")
    if density_family is not None and density_family not in DENSITY_FAMILIES:
        raise ValueError(
            _t("{hint}: 'density_family' muss None oder eines von {density_families} sein, ist {density_family!r}", hint=hint, density_families=DENSITY_FAMILIES, density_family=density_family))

    return TapeProfile(id=tape_id, name=name, background=background, ink=ink, material=material,
                        transparent=transparent, code_mode=code_mode, density=density,
                        density_family=density_family)


def _load_tapes(text: str, hint) -> list[TapeProfile]:
    raw = json.loads(text)
    return [_parse_tape(item, hint) for item in raw]


def builtin_tapes() -> list[TapeProfile]:
    text = resources.files("tapesmith.tape").joinpath("tapes.json").read_text(encoding="utf-8")
    return _load_tapes(text, "tapes.json")


def user_tapes_path() -> Path:
    return paths.app_dir() / "tapes.json"


def list_tapes() -> list[TapeProfile]:
    """Eingebaute Bänder, ergänzt/überschrieben durch die Benutzerdatei (gleiche id
    überschreibt); Reihenfolge: eingebaut, dann neu hinzugekommene."""
    tapes: dict[str, TapeProfile] = {t.id: t for t in builtin_tapes()}
    order = list(tapes)
    path = user_tapes_path()
    if path.exists():
        for t in _load_tapes(path.read_text(encoding="utf-8"), str(path)):
            if t.id not in tapes:
                order.append(t.id)
            tapes[t.id] = t
    return [tapes[i] for i in order]


def find_tape(tape_id: str) -> TapeProfile:
    for t in list_tapes():
        if t.id == tape_id:
            return t
    available = ", ".join(t.id for t in list_tapes())
    raise ValueError(_t("Band '{tape_id}' unbekannt (vorhanden: {available})", tape_id=tape_id, available=available))


def current_tape(cfg: dict) -> TapeProfile:
    """Das per `config.tape_setting` gewählte Band; unbekannte id -> DEFAULT_TAPE."""
    tape_id = config.tape_setting(cfg)
    try:
        return find_tape(tape_id)
    except ValueError:
        return find_tape(DEFAULT_TAPE)


def save_tape_density(tape_id: str, value: int | None, family: str | None, *,
                      path: Path | None = None) -> TapeProfile:
    """Speichert (oder löscht) den experimentellen Dichte-Kandidaten eines Bandes in der
    Benutzerdatei. Wird **nie** automatisch an den Drucker gesendet."""
    if family is not None and family not in DENSITY_FAMILIES:
        raise ValueError(_t("'density_family' muss None oder eines von {density_families} sein, ist {family!r}", density_families=DENSITY_FAMILIES, family=family))
    find_tape(tape_id)  # unbekanntes Band -> ValueError

    target = path if path is not None else user_tapes_path()
    raw_list = json.loads(target.read_text(encoding="utf-8")) if target.exists() else []
    entries: dict[str, dict] = {item["id"]: item for item in raw_list}
    if tape_id not in entries:
        builtin_text = resources.files("tapesmith.tape").joinpath("tapes.json").read_text(encoding="utf-8")
        builtin_raw = json.loads(builtin_text)
        entries[tape_id] = dict(next(item for item in builtin_raw if item["id"] == tape_id))

    entry = entries[tape_id]
    if value is None:
        entry.pop("density", None)
        entry.pop("density_family", None)
    else:
        entry["density"] = value
        entry["density_family"] = family

    fileutil.atomic_write_text(target, json.dumps(list(entries.values()), indent=2))
    if path is not None:
        return _parse_tape(entry, str(target))
    return find_tape(tape_id)
