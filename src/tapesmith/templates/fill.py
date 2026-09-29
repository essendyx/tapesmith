"""Vorlagen füllen: Eingaben, feste Werte, Datum, Zähler, Nachschlagewerte, Filter und sensible Felder."""

import calendar
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from tapesmith.document.model import LabelDocument, map_texts
from tapesmith.fileutil import FileLock, atomic_write_text
from tapesmith.render.compose import LabelSpec
from tapesmith.templates.model import Field, Template, TemplateError, expand
from tapesmith.templates.serial import SerialNotDerivable, normalize_serial_input
from tapesmith.i18n import _t

REDACTED = "•••"


class CounterStore:
    def __init__(self, path: Path):
        self.path = Path(path)

    def _load(self) -> dict:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def peek(self, key: str) -> int:
        return int(self._load().get(key, 0)) + 1

    def commit(self, key: str) -> int:
        lock_path = self.path.with_name(self.path.name + ".lock")
        with FileLock(lock_path):
            data = self._load()
            value = int(data.get(key, 0)) + 1
            data[key] = value
            atomic_write_text(self.path, json.dumps(data, indent=2))
            return value


@dataclass(frozen=True)
class Resolved:
    values: dict[str, str]
    counter_keys: tuple[str, ...]


def _parse_date(text: str, label: str) -> datetime:
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise TemplateError(_t("Feld '{label}': Datum '{text}' nicht lesbar (TT.MM.JJJJ)", label=label, text=text))


def _add_months(dt: datetime, months: int) -> datetime:
    total = dt.month - 1 + months
    year = dt.year + total // 12
    month = total % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def _int_from_field(values: dict[str, str], field_id: str, label: str) -> int:
    raw = values.get(field_id, "")
    try:
        return int(raw)
    except ValueError:
        raise TemplateError(_t("Feld '{label}': '{raw}' ist keine ganze Zahl", label=label, raw=raw)) from None


def resolve_values(template: Template, inputs: dict[str, str], now: datetime, counters: CounterStore,
                    *, counter_offset: int = 0) -> Resolved:
    known = {f.id for f in template.fields}
    size_field = template.text_size_field
    implicit_size = template.text_size_implicit
    if implicit_size:
        known.add(size_field.id)
    unknown = set(inputs) - known
    if unknown:
        raise TemplateError(_t("Vorlage '{name}': unbekannte Felder {sorted}", name=template.name, sorted=sorted(unknown)))
    not_settable = {f.id: f for f in template.fields if f.type != "input"}
    for fid in sorted(set(inputs) & set(not_settable)):
        raise TemplateError(_t("Vorlage '{name}': Feld '{label}' ist nicht eingebbar", name=template.name, label=not_settable[fid].label))

    values: dict[str, str] = {}
    counter_keys: list[str] = []

    # 1) fixed/input/counter in Feldreihenfolge
    for f in template.fields:
        if f.type == "fixed":
            values[f.id] = f.default
        elif f.type == "input":
            value = inputs.get(f.id, f.default).strip()
            if f.required and not value:
                raise TemplateError(_t("Vorlage '{name}': Feld '{label}' fehlt", name=template.name, label=f.label))
            if f.clean == "serial" and value:
                try:
                    disk = normalize_serial_input(value)
                except SerialNotDerivable as exc:
                    raise TemplateError(str(exc)) from exc
                value = disk.serial
                values[f"{f.id}_model"] = disk.model or ""
            elif f.clean == "serial":
                values[f"{f.id}_model"] = ""
            values[f.id] = value
        elif f.type == "counter":
            key = f"{template.name}.{f.id}"
            values[f.id] = (f.format or "{:d}").format(counters.peek(key) + counter_offset)
            counter_keys.append(key)

    # Implizites Feld schriftgroesse: nur übernehmen, wenn gesetzt (sonst gilt der Standard).
    if implicit_size and inputs.get(size_field.id, "").strip():
        values[size_field.id] = inputs[size_field.id].strip()

    # 2) alle lookup (Quellfeld kann in beliebiger Position deklariert sein)
    for f in template.fields:
        if f.type == "lookup":
            values[f.id] = f.lookup(values.get(f.source, ""))

    # 3) alle date (kann auf lookup-/input-Werte zugreifen)
    for f in template.fields:
        if f.type != "date":
            continue
        base = now
        if f.base_field:
            base = _parse_date(values.get(f.base_field, ""), template.field(f.base_field).label)
        days = f.offset_days
        if f.offset_field:
            days += _int_from_field(values, f.offset_field, template.field(f.offset_field).label)
        months = f.offset_months
        if f.offset_months_field:
            months += _int_from_field(values, f.offset_months_field, template.field(f.offset_months_field).label)
        result = _add_months(base, months) + timedelta(days=days)
        values[f.id] = result.strftime(f.format or "%d.%m.%Y")

    return Resolved(values, tuple(counter_keys))


def build_spec(template: Template, values: dict[str, str]) -> LabelSpec:
    if template.kind != "layout":
        raise TemplateError(_t("Vorlage '{name}' hat kein layout", name=template.name))
    layout = dict(template.layout)
    layout["lines"] = tuple(expand(line, values) for line in layout.get("lines", []))
    if isinstance(layout.get("qr"), str):
        layout["qr"] = expand(layout["qr"], values) or None
    return LabelSpec(**layout)


def build_document(template: Template, values: dict[str, str]) -> LabelDocument:
    if template.document is None:
        raise TemplateError(_t("Vorlage '{name}' hat kein document", name=template.name))
    return map_texts(template.document, lambda s: expand(s, values))


def input_fields(template: Template) -> tuple[Field, ...]:
    """Nur Felder vom Typ `input` (für Formular/Import)."""
    return tuple(f for f in template.fields if f.type == "input")


def form_fields(template: Template) -> tuple[Field, ...]:
    """Alle Felder fürs Formular: `fields` plus das implizite Feld schriftgroesse (am Ende)."""
    if template.text_size_implicit:
        return template.fields + (template.text_size_field,)
    return template.fields


def redact(template: Template, values: dict[str, str]) -> dict[str, str]:
    secret = {f.id for f in template.fields if f.secret}
    masked = secret | {f"{fid}_model" for fid in secret}
    return {k: (REDACTED if k in masked else v) for k, v in values.items()}


def redact_text(text: str, template: Template, values: dict[str, str]) -> str:
    """Ersetzt jedes Vorkommen eines nicht-leeren Werts eines sensiblen Felds (und seines
    zugehörigen `_model`-Werts) in text durch REDACTED. Längere Werte zuerst, damit kein
    Teilstring eines längeren Geheimwerts vorher unvollständig maskiert wird."""
    secret_ids = {f.id for f in template.fields if f.secret}
    keys = [k for k in values if k in secret_ids or (k.endswith("_model") and k[:-len("_model")] in secret_ids)]
    needles = sorted({values[k] for k in keys if values[k]}, key=len, reverse=True)
    for needle in needles:
        text = text.replace(needle, REDACTED)
    return text
