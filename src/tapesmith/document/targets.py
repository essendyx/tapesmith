"""Zielobjekte: Maximal-/Festlänge je Zielobjekt, Kürzungsregeln für Vorlagen.

Mitgeliefert über `targets.json`, ergänzt/überschrieben durch die Benutzerdatei
`%APPDATA%\\Tapesmith\\targets.json` (gleiche id überschreibt), analog zu `tape.profiles`.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from tapesmith import i18n, paths
from tapesmith.i18n import _t

RULES = ("last", "first", "strip_domain")

_IPV4 = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")


@dataclass(frozen=True)
class TargetProfile:
    id: str
    name: str
    max_length_mm: float | None = None
    fixed_length_mm: float | None = None
    note: str = ""


@dataclass(frozen=True)
class ShortenRule:
    field: str
    rule: str
    n: int | None = None

    def apply(self, value: str) -> str:
        if self.rule == "last":
            return value[-self.n:] if self.n else value
        if self.rule == "first":
            return value[:self.n]
        if self.rule == "strip_domain":
            if _IPV4.match(value):
                return value
            return value.split(".", 1)[0]
        raise ValueError(_t("Unbekannte Kürzungsregel '{rule}' (erlaubt: {items})", rule=self.rule, items=', '.join(RULES)))

    def describe(self, field_label: str) -> str:
        if self.rule == "last":
            return _t("{field_label}: letzte {n} Stellen", field_label=field_label, n=self.n)
        if self.rule == "first":
            return _t("{field_label}: erste {n} Zeichen", field_label=field_label, n=self.n)
        if self.rule == "strip_domain":
            return _t("{field_label}: ohne Domain", field_label=field_label)
        raise ValueError(_t("Unbekannte Kürzungsregel '{rule}' (erlaubt: {items})", rule=self.rule, items=', '.join(RULES)))


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _parse_target(raw: dict, hint) -> TargetProfile:
    try:
        target_id = raw["id"]
        name = raw["name"]
    except KeyError as exc:
        raise ValueError(_t("{hint}: Zielobjekt unvollständig, Schlüssel fehlt: {exc}", hint=hint, exc=exc)) from exc

    max_length = raw.get("max_length_mm")
    fixed_length = raw.get("fixed_length_mm")
    if (max_length is None) == (fixed_length is None):
        raise ValueError(
            _t("{hint}: Zielobjekt '{target_id}' braucht genau eins von max_length_mm/fixed_length_mm", hint=hint, target_id=target_id))
    for key, value in (("max_length_mm", max_length), ("fixed_length_mm", fixed_length)):
        if value is not None and (not _is_number(value) or value <= 0):
            raise ValueError(_t("{hint}: Zielobjekt '{target_id}': '{key}' muss eine Zahl > 0 sein", hint=hint, target_id=target_id, key=key))

    note = raw.get("note", "")
    if not isinstance(note, str):
        raise ValueError(_t("{hint}: Zielobjekt '{target_id}': 'note' muss Text sein", hint=hint, target_id=target_id))
    translations = raw.get("translations") or {}
    if not isinstance(translations, dict) or not all(
            isinstance(block, dict) and all(isinstance(block.get(k, ""), str) for k in ("name", "note"))
            for block in translations.values()):
        raise ValueError(_t("{hint}: Zielobjekt '{target_id}': 'translations' muss je Sprache ein Objekt mit "
                            "den Texten 'name' und 'note' sein", hint=hint, target_id=target_id))
    # Anzeigename und Hinweis in der Sprache der Anfrage, die id bleibt.
    block = translations.get(i18n.language()) or {}
    name = block.get("name") or name
    note = block.get("note") or note

    return TargetProfile(
        id=target_id, name=name,
        max_length_mm=float(max_length) if max_length is not None else None,
        fixed_length_mm=float(fixed_length) if fixed_length is not None else None,
        note=note,
    )


def _load_targets(text: str, hint) -> list[TargetProfile]:
    raw = json.loads(text)
    return [_parse_target(item, hint) for item in raw]


def builtin_targets() -> list[TargetProfile]:
    text = resources.files("tapesmith.document").joinpath("targets.json").read_text(encoding="utf-8")
    return _load_targets(text, "targets.json")


def user_targets_path() -> Path:
    return paths.app_dir() / "targets.json"


def load_targets() -> list[TargetProfile]:
    """Eingebaute Zielobjekte, ergänzt/überschrieben durch die Benutzerdatei (gleiche id
    überschreibt); Reihenfolge: eingebaut, dann neu hinzugekommene."""
    targets: dict[str, TargetProfile] = {t.id: t for t in builtin_targets()}
    order = list(targets)
    path = user_targets_path()
    if path.exists():
        for t in _load_targets(path.read_text(encoding="utf-8"), str(path)):
            if t.id not in targets:
                order.append(t.id)
            targets[t.id] = t
    return [targets[i] for i in order]


def find_target(target_id: str) -> TargetProfile:
    for t in load_targets():
        if t.id == target_id:
            return t
    available = ", ".join(t.id for t in load_targets())
    raise ValueError(_t("Zielobjekt '{target_id}' unbekannt (vorhanden: {available})", target_id=target_id, available=available))


def shorten_steps(
    values: Mapping[str, str], rules: Sequence[ShortenRule], labels: Mapping[str, str]
) -> list[tuple[dict[str, str], tuple[str, ...]]]:
    """[(values, ())] + je Regel, die etwas ändert, ein kumulativer Schritt
    (neue Werte, Beschreibungen aller bisher wirksamen Kürzungen)."""
    steps: list[tuple[dict[str, str], tuple[str, ...]]] = [(dict(values), ())]
    current = dict(values)
    descriptions: tuple[str, ...] = ()
    for rule in rules:
        before = current.get(rule.field, "")
        after = rule.apply(before)
        if after == before:
            continue
        current = dict(current)
        current[rule.field] = after
        descriptions = descriptions + (rule.describe(labels.get(rule.field, rule.field)),)
        steps.append((dict(current), descriptions))
    return steps
