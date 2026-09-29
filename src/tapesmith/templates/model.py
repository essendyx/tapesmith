"""Vorlagen-Dateiformat (*.tapesmith.json): Schema, Validierung, Migration."""

import dataclasses
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from tapesmith import __version__
from tapesmith.document.generators import GENERATORS, GeneratorRef
from tapesmith.document.model import DocumentError, LabelDocument, document_from_dict, document_to_dict, texts
from tapesmith.document.targets import RULES, ShortenRule, find_target
from tapesmith.document.model import TextObject
from tapesmith.render import textsize
from tapesmith.render.compose import LabelSpec
from tapesmith.render.fonts import FONT_FILES
from tapesmith.render.text import ALIGNS
from tapesmith.tape.suitability import validate_allowed
from tapesmith import i18n
from tapesmith.i18n import _t


def migrate_v1_to_v2(data: dict) -> dict:
    """Inhaltlich unverändert: `layout` bleibt `layout`. Das `setdefault` ist nur ein
    Sicherheitsnetz, falls eine v1-Datei je ohne den (in v1 pflichtigen) Layout-Schlüssel
    aufgetaucht wäre; jede reguläre v1-Datei ist danach weiterhin gültig."""
    data = dict(data)
    data.setdefault("layout", {})
    return data


SCHEMA_VERSION = 2
MIGRATIONS: dict[int, Callable[[dict], dict]] = {1: migrate_v1_to_v2}
FIELD_TYPES = ("fixed", "input", "date", "counter", "lookup")
CLEANERS = ("serial",)
QR_ERROR_LEVELS = ("l", "m", "q", "h")
TOP_LEVEL_KEYS = ("schema_version", "name", "description", "fields", "layout", "document", "generator",
                  "category", "tags", "sample", "target", "shorten", "tapes", "default_copies", "checks",
                  "min_app_version", "text_height", "title", "translations")
# Übersetzungsblock `translations.<sprache>` (siehe `localize_data`): erlaubte Schlüssel.
TRANSLATION_KEYS = ("title", "description", "category", "tags", "fields", "sample", "lines", "texts")
TRANSLATION_FIELD_KEYS = ("label", "default", "choices", "map", "choice_labels")
PLACEHOLDER = re.compile(r"\{([a-z][a-z0-9_]*)(?:\|([^}]*))?\}")
_FIELD_ID = re.compile(r"^[a-z][a-z0-9_]*$")
_LAYOUT_KEYS = {f.name for f in dataclasses.fields(LabelSpec)}
_PROBE_NOW = datetime(2026, 1, 2, 3, 4, 5)


class TemplateError(ValueError):
    pass


class TemplateNotFound(TemplateError):
    """Vorlage mit diesem Namen gibt es nicht (weder eigene noch mitgelieferte)."""


@dataclass(frozen=True)
class Field:
    id: str
    label: str
    type: str
    default: str = ""
    required: bool = False
    secret: bool = False
    choices: tuple[str, ...] = ()
    clean: str | None = None
    format: str | None = None
    offset_days: int = 0
    source: str | None = None                 # lookup: Quellfeld
    map: tuple[tuple[str, str], ...] = ()      # lookup: Wert -> Ergebnis (Reihenfolge erhalten)
    base_field: str | None = None              # date: Basisdatum aus Feld; leer -> jetzt
    offset_months: int = 0                     # date
    offset_field: str | None = None            # date: Tage aus Feld (ganze Zahl)
    offset_months_field: str | None = None     # date: Monate aus Feld (ganze Zahl)
    max_len: int | None = None                 # input: maximale Länge (Lint-Testdaten, GUI-Begrenzung)
    multiline: bool = False                    # input: mehrzeilig (Raster-Belegung)
    choice_labels: tuple[tuple[str, str], ...] = ()   # Anzeige je Auswahlwert (Wert bleibt, was druckt)
    # lookup: Einträge der Tabellen anderer Sprachen (nicht gespeichert), damit ein in einer anderen
    # Sprache gewählter Wert (z. B. aus dem Verlauf) weiter aufgelöst wird.
    alt_map: tuple[tuple[str, str], ...] = dataclasses.field(default=(), compare=False, repr=False)

    def map_dict(self) -> dict[str, str]:
        return dict(self.map)

    def lookup(self, key: str) -> str:
        """Wert der lookup-Tabelle, sonst aus den Tabellen anderer Sprachen, sonst leer."""
        for k, v in self.map:
            if k == key:
                return v
        for k, v in self.alt_map:
            if k == key:
                return v
        return ""

    def choice_label(self, value: str) -> str:
        return dict(self.choice_labels).get(value, value)


_FIELD_KEYS = tuple(f.name for f in dataclasses.fields(Field) if f.name != "alt_map")


def apply_filter(value: str, spec: str) -> str:
    name, _, arg = spec.partition(":")
    if name == "last" and arg.isdigit():
        n = int(arg)
        if n == 0:
            raise TemplateError(_t("Filter '{spec}': last:0 ist nicht erlaubt (N muss > 0 sein)", spec=spec))
        return value[-n:]
    if name == "first" and arg.isdigit():
        n = int(arg)
        if n == 0:
            raise TemplateError(_t("Filter '{spec}': first:0 ist nicht erlaubt (N muss > 0 sein)", spec=spec))
        return value[:n]
    if name == "upper" and not arg:
        return value.upper()
    if name == "lower" and not arg:
        return value.lower()
    raise TemplateError(_t("Unbekannter Filter '{spec}' (erlaubt: last:N, first:N, upper, lower)", spec=spec))


def expand(text: str, values: dict[str, str]) -> str:
    def replace(match):
        name, filters = match.group(1), match.group(2)
        if name not in values:
            raise TemplateError(_t("Platzhalter '{{{name}}}' ist unbekannt", name=name))
        value = values[name]
        for spec in filter(None, (filters or "").split("|")):
            value = apply_filter(value, spec)
        return value

    return PLACEHOLDER.sub(replace, text)


@dataclass(frozen=True)
class Template:
    name: str
    description: str
    fields: tuple[Field, ...]
    layout: dict
    schema_version: int
    min_app_version: str | None = None
    path: Path | None = None
    document: LabelDocument | None = None
    generator: GeneratorRef | None = None
    category: str = ""
    tags: tuple[str, ...] = ()
    sample: dict[str, str] = dataclasses.field(default_factory=dict)
    target: str | None = None
    shorten: tuple[ShortenRule, ...] = ()
    tapes: tuple[str, ...] = ()
    default_copies: int = 1
    checks: dict = dataclasses.field(default_factory=dict)
    text_height: str | bool | None = None     # Schema-Wert text_height (kanonisch), False = aus
    text_size_field: Field | None = None      # Feld schriftgroesse (deklariert oder implizit), sonst None
    title: str = ""                           # Anzeigename (Standard: `name`, die stabile ID)
    translations: dict = dataclasses.field(default_factory=dict, compare=False, repr=False)
    language: str | None = None               # Sprache, in der die Vorlage aufgebaut wurde
    localized: bool = False                   # True: ein Übersetzungsblock wurde angewendet
    source: dict | None = dataclasses.field(default=None, compare=False, repr=False)  # Rohdaten

    @property
    def display_title(self) -> str:
        return self.title or self.name

    def field(self, field_id: str) -> Field:
        for f in self.fields:
            if f.id == field_id:
                return f
        raise TemplateError(_t("Vorlage '{name}': Feld '{field_id}' gibt es nicht", name=self.name, field_id=field_id))

    @property
    def text_size_implicit(self) -> bool:
        """True, wenn das Feld `schriftgroesse` nicht in `fields` steht, sondern ergänzt wurde."""
        return self.text_size_field is not None and self.text_size_field not in self.fields

    @property
    def text_size_per_field(self) -> bool:
        """Nur Raster-Vorlagen kennen "auto-feld" (jedes Feld einzeln eingepasst)."""
        return self.generator is not None and self.generator.name == "raster"

    @property
    def kind(self) -> str:
        if self.document is not None:
            return "document"
        if self.generator is not None:
            return "generator"
        return "layout"


def _supports_text_size(layout: dict, document: LabelDocument | None, generator: GeneratorRef | None) -> bool:
    """Einstellbare Schriftgröße nur, wo Text automatisch eingepasst wird: Raster-Generator,
    Kurzform mit Zeilen ohne feste font_size, Dokument mit mindestens einem waagrechten
    Textobjekt ohne feste Größe."""
    if generator is not None:
        return generator.name == "raster"
    if document is not None:
        return any(isinstance(o, TextObject) and o.size is None and not o.vertical for o in document.objects)
    return bool(layout.get("lines")) and layout.get("font_size") is None


def _check_text_size_value(value, per_field: bool, what: str) -> str:
    try:
        canon = textsize.canonical(value)
    except textsize.TextSizeError as exc:
        raise TemplateError(f"{what}: {exc}") from exc
    if canon == textsize.AUTO_FIELD and not per_field:
        raise TemplateError(_t("{what}: 'auto-feld' gibt es nur bei Raster-Vorlagen", what=what))
    return canon


def _text_size_fields(fields: tuple[Field, ...], data: dict, layout: dict, document, generator,
                      where: str) -> tuple[Field | None, str | bool | None]:
    per_field = generator is not None and generator.name == "raster"
    supported = _supports_text_size(layout, document, generator)
    text_height: str | bool | None = None
    if "text_height" in data:
        raw = data["text_height"]
        if raw is False:
            text_height = False
        else:
            if not supported:
                raise TemplateError(_t("{where}: text_height nur bei Vorlagen mit automatisch eingepasstem Text", where=where))
            text_height = _check_text_size_value(raw, per_field, _t("{where}: text_height", where=where))
    if not supported or text_height is False:
        return None, text_height

    declared = next((f for f in fields if f.id == textsize.TEXT_SIZE_FIELD), None)
    if declared is not None:
        what = _t("{where}: Feld '{text_size_field}'", where=where, text_size_field=textsize.TEXT_SIZE_FIELD)
        if declared.type != "input":
            raise TemplateError(_t("{what} muss vom Typ 'input' sein", what=what))
        if declared.default:
            _check_text_size_value(declared.default, per_field, what)
        for choice in declared.choices:
            _check_text_size_value(choice, per_field, what)
        return declared, text_height

    default = text_height if isinstance(text_height, str) else textsize.AUTO
    implicit = Field(id=textsize.TEXT_SIZE_FIELD, label=_t(textsize.TEXT_SIZE_LABEL), type="input",
                     default=default, choices=textsize.choices(per_field))
    return implicit, text_height


def _version_tuple(text: str) -> tuple[int, ...]:
    return tuple(int(p) for p in re.findall(r"\d+", text))


def _layout_strings(layout: dict) -> list[str]:
    strings = [s for s in layout.get("lines", []) if isinstance(s, str)]
    if isinstance(layout.get("qr"), str):
        strings.append(layout["qr"])
    return strings


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _check_placeholders(strings: list[str], known: set[str], dummy: dict[str, str], where: str) -> None:
    for text in strings:
        for name, _filters in PLACEHOLDER.findall(text):
            if name not in known:
                raise TemplateError(_t("{where}: Platzhalter '{{{name}}}' verweist auf unbekanntes Feld", where=where, name=name))
        try:
            expand(text, dummy)
        except TemplateError as exc:
            raise TemplateError(f"{where}: {exc}") from exc


def _check_layout(layout: dict, where: str) -> None:
    lines = layout.get("lines")
    if lines is not None:
        if not (isinstance(lines, list) and 1 <= len(lines) <= 3 and all(isinstance(s, str) for s in lines)):
            raise TemplateError(_t("{where}: layout.lines muss eine Liste von 1 bis 3 Zeichenketten sein", where=where))
    font = layout.get("font")
    if font is not None and font not in FONT_FILES:
        raise TemplateError(_t("{where}: layout.font '{font}' unbekannt (erlaubt: {items})", where=where, font=font, items=', '.join(FONT_FILES)))
    align = layout.get("align")
    if align is not None and align not in ALIGNS:
        raise TemplateError(_t("{where}: layout.align '{align}' unbekannt (erlaubt: {items})", where=where, align=align, items=', '.join(ALIGNS)))
    qr_error = layout.get("qr_error")
    if qr_error is not None and (not isinstance(qr_error, str) or qr_error.lower() not in QR_ERROR_LEVELS):
        raise TemplateError(_t("{where}: layout.qr_error '{qr_error}' unbekannt (erlaubt: {items})", where=where, qr_error=qr_error, items=', '.join(QR_ERROR_LEVELS)))
    font_size = layout.get("font_size")
    if font_size is not None and (type(font_size) is not int or font_size <= 0):
        raise TemplateError(_t("{where}: layout.font_size muss eine ganze Zahl > 0 sein", where=where))
    for key in ("max_length_mm", "fixed_length_mm", "margin_mm"):
        value = layout.get(key)
        if value is None:
            continue
        if not _is_number(value):
            raise TemplateError(_t("{where}: layout.{key} muss eine Zahl sein", where=where, key=key))
        if key == "margin_mm":
            if value < 0:
                raise TemplateError(_t("{where}: layout.{key} darf nicht negativ sein", where=where, key=key))
        elif value <= 0:
            raise TemplateError(_t("{where}: layout.{key} muss größer als 0 sein", where=where, key=key))
    qr = layout.get("qr")
    if qr is not None and not isinstance(qr, str):
        raise TemplateError(_t("{where}: layout.qr muss Text oder null sein", where=where))


def _build_fields(raw_fields: list, where: str) -> tuple[tuple[Field, ...], set[str]]:
    seen_ids: set[str] = set()
    for raw in raw_fields:
        unknown = set(raw) - set(_FIELD_KEYS)
        if unknown:
            raise TemplateError(_t("{where}: unbekannte Feld-Eigenschaften {sorted}", where=where, sorted=sorted(unknown)))
        fid = raw.get("id", "")
        if not _FIELD_ID.match(fid):
            raise TemplateError(_t("{where}: ungültige Feld-ID '{fid}' (nur a-z, 0-9, _; Beginn mit Buchstabe)", where=where, fid=fid))
        if fid in seen_ids:
            raise TemplateError(_t("{where}: Feld-ID '{fid}' doppelt", where=where, fid=fid))
        seen_ids.add(fid)

    fields: list[Field] = []
    for raw in raw_fields:
        fid = raw["id"]
        ftype = raw.get("type")
        if ftype not in FIELD_TYPES:
            raise TemplateError(_t("{where}: Feld '{fid}' hat unbekannten Typ '{ftype}' (erlaubt: {items})", where=where, fid=fid, ftype=ftype, items=', '.join(FIELD_TYPES)))
        clean = raw.get("clean")
        if clean is not None:
            if ftype != "input":
                raise TemplateError(_t("{where}: Feld '{fid}': clean ist nur bei Typ 'input' zulässig", where=where, fid=fid))
            if clean not in CLEANERS:
                raise TemplateError(_t("{where}: Feld '{fid}': clean '{clean}' unbekannt (erlaubt: {items})", where=where, fid=fid, clean=clean, items=', '.join(CLEANERS)))
        offset_days_raw = raw.get("offset_days", 0)
        if isinstance(offset_days_raw, bool) or not isinstance(offset_days_raw, int):
            raise TemplateError(_t("{where}: Feld '{fid}': offset_days muss eine ganze Zahl sein", where=where, fid=fid))
        fmt = raw.get("format")
        if fmt is not None and ftype == "counter":
            try:
                fmt.format(1)
            except Exception as exc:
                raise TemplateError(_t("{where}: Feld '{fid}': format '{fmt}' ungültig ({exc})", where=where, fid=fid, fmt=fmt, exc=exc)) from exc
        elif fmt is not None and ftype == "date":
            try:
                _PROBE_NOW.strftime(fmt)
            except Exception as exc:
                raise TemplateError(_t("{where}: Feld '{fid}': format '{fmt}' ungültig ({exc})", where=where, fid=fid, fmt=fmt, exc=exc)) from exc

        source = raw.get("source")
        map_raw = raw.get("map")
        if ftype == "lookup":
            if not isinstance(source, str) or source not in seen_ids:
                raise TemplateError(_t("{where}: Feld '{fid}': lookup braucht ein vorhandenes Feld 'source'", where=where, fid=fid))
            if not isinstance(map_raw, dict) or not all(
                isinstance(k, str) and isinstance(v, str) for k, v in map_raw.items()
            ):
                raise TemplateError(_t("{where}: Feld '{fid}': map muss ein Objekt Text->Text sein", where=where, fid=fid))
            map_tuple = tuple(map_raw.items())
        else:
            if source is not None:
                raise TemplateError(_t("{where}: Feld '{fid}': source ist nur bei Typ 'lookup' zulässig", where=where, fid=fid))
            if map_raw is not None:
                raise TemplateError(_t("{where}: Feld '{fid}': map ist nur bei Typ 'lookup' zulässig", where=where, fid=fid))
            source = None
            map_tuple = ()

        base_field = raw.get("base_field")
        offset_field = raw.get("offset_field")
        offset_months_field = raw.get("offset_months_field")
        offset_months_raw = raw.get("offset_months", 0)
        refs = (("base_field", base_field), ("offset_field", offset_field),
                ("offset_months_field", offset_months_field))
        if ftype == "date":
            for ref_name, ref_val in refs:
                if ref_val is not None and (not isinstance(ref_val, str) or ref_val not in seen_ids):
                    raise TemplateError(_t("{where}: Feld '{fid}': {ref_name} verweist auf unbekanntes Feld '{ref_val}'", where=where, fid=fid, ref_name=ref_name, ref_val=ref_val))
            if isinstance(offset_months_raw, bool) or not isinstance(offset_months_raw, int):
                raise TemplateError(_t("{where}: Feld '{fid}': offset_months muss eine ganze Zahl sein", where=where, fid=fid))
        else:
            for ref_name, ref_val in refs:
                if ref_val is not None:
                    raise TemplateError(_t("{where}: Feld '{fid}': {ref_name} ist nur bei Typ 'date' zulässig", where=where, fid=fid, ref_name=ref_name))
            if offset_months_raw:
                raise TemplateError(_t("{where}: Feld '{fid}': offset_months ist nur bei Typ 'date' zulässig", where=where, fid=fid))

        max_len_raw = raw.get("max_len")
        if max_len_raw is not None:
            if ftype != "input":
                raise TemplateError(_t("{where}: Feld '{fid}': max_len ist nur bei Typ 'input' zulässig", where=where, fid=fid))
            if isinstance(max_len_raw, bool) or not isinstance(max_len_raw, int) or max_len_raw <= 0:
                raise TemplateError(_t("{where}: Feld '{fid}': max_len muss eine ganze Zahl > 0 sein", where=where, fid=fid))

        multiline_raw = raw.get("multiline", False)
        if not isinstance(multiline_raw, bool):
            raise TemplateError(_t("{where}: Feld '{fid}': multiline muss wahr/falsch sein", where=where, fid=fid))
        if multiline_raw and ftype != "input":
            raise TemplateError(_t("{where}: Feld '{fid}': multiline ist nur bei Typ 'input' zulässig", where=where, fid=fid))

        labels_raw = raw.get("choice_labels")
        if labels_raw is None:
            labels_tuple: tuple[tuple[str, str], ...] = ()
        else:
            if not isinstance(labels_raw, dict) or not all(
                    isinstance(k, str) and isinstance(v, str) for k, v in labels_raw.items()):
                raise TemplateError(_t("{where}: Feld '{fid}': choice_labels muss ein Objekt Text->Text sein",
                                       where=where, fid=fid))
            unknown_choices = set(labels_raw) - set(raw.get("choices", ()))
            if unknown_choices:
                raise TemplateError(_t("{where}: Feld '{fid}': choice_labels nennt Werte, die nicht in choices "
                                       "stehen: {items}", where=where, fid=fid, items=", ".join(sorted(unknown_choices))))
            labels_tuple = tuple(labels_raw.items())

        fields.append(Field(
            id=fid, label=raw.get("label", fid), type=ftype, default=str(raw.get("default", "")),
            required=bool(raw.get("required", False)), secret=bool(raw.get("secret", False)),
            choices=tuple(raw.get("choices", ())), clean=clean, format=fmt,
            offset_days=offset_days_raw, source=source, map=map_tuple,
            base_field=base_field, offset_months=offset_months_raw, offset_field=offset_field,
            offset_months_field=offset_months_field, max_len=max_len_raw, multiline=multiline_raw,
            choice_labels=labels_tuple,
        ))
    return tuple(fields), seen_ids


def _is_str_list(value) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


def _is_str_dict(value) -> bool:
    return isinstance(value, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in value.items())


def _check_translation_fields(block: dict, fields: dict, what: str) -> None:
    field_block = block.get("fields", {})
    if not isinstance(field_block, dict):
        raise TemplateError(_t("{what}.fields muss ein Objekt sein", what=what))
    for fid, entry in field_block.items():
        if fid not in fields:
            raise TemplateError(_t("{what}.fields: Feld '{fid}' gibt es nicht", what=what, fid=fid))
        if not isinstance(entry, dict):
            raise TemplateError(_t("{what}.fields.{fid} muss ein Objekt sein", what=what, fid=fid))
        unknown = set(entry) - set(TRANSLATION_FIELD_KEYS)
        if unknown:
            raise TemplateError(_t("{what}.fields.{fid}: unbekannte Schlüssel {items}", what=what, fid=fid,
                                   items=sorted(unknown)))
        for key in ("label", "default"):
            if key in entry and not isinstance(entry[key], str):
                raise TemplateError(_t("{what}.fields.{fid}.{key} muss Text sein", what=what, fid=fid, key=key))
        if "choices" in entry:
            base_choices = fields[fid].get("choices")
            if not _is_str_list(entry["choices"]) or not isinstance(base_choices, list) \
                    or len(entry["choices"]) != len(base_choices):
                raise TemplateError(_t("{what}.fields.{fid}.choices braucht genau so viele Werte wie choices",
                                       what=what, fid=fid))
        for key in ("map", "choice_labels"):
            if key in entry and not _is_str_dict(entry[key]):
                raise TemplateError(_t("{what}.fields.{fid}.{key} muss ein Objekt Text->Text sein", what=what,
                                       fid=fid, key=key))
        if "map" in entry and fields[fid].get("type") != "lookup":
            raise TemplateError(_t("{what}.fields.{fid}.map nur bei Typ 'lookup'", what=what, fid=fid))


def check_translations(data: dict, where: str) -> dict[str, dict]:
    """Prüft den Block `translations` (Aufbau, bekannte Felder und Objekte) und gibt ihn zurück.

    Form: `{"en": {"title", "description", "category", "tags", "fields": {feld: {"label",
    "default", "choices", "map", "choice_labels"}}, "sample", "lines", "texts": {objekt-id: text}}}`,
    alle Schlüssel optional. Die übersetzte Vorlage selbst prüft `template_from_dict(..., lang=...)`."""
    raw = data.get("translations")
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise TemplateError(_t("{where}: translations muss ein Objekt sein", where=where))
    fields = {f.get("id"): f for f in data.get("fields", []) if isinstance(f, dict)}
    objects = {}
    document = data.get("document")
    if isinstance(document, dict):
        objects = {o.get("id"): o for o in document.get("objects", []) if isinstance(o, dict)}
    layout = data.get("layout") if isinstance(data.get("layout"), dict) else {}
    for lang, block in raw.items():
        what = f"{where}: translations.{lang}"
        if lang not in i18n.LANGUAGES or lang == i18n.FALLBACK:
            raise TemplateError(_t("{what}: Sprache unbekannt (erlaubt: {items})", what=what,
                                   items=", ".join(x for x in i18n.LANGUAGES if x != i18n.FALLBACK)))
        if not isinstance(block, dict):
            raise TemplateError(_t("{what} muss ein Objekt sein", what=what))
        unknown = set(block) - set(TRANSLATION_KEYS)
        if unknown:
            raise TemplateError(_t("{what}: unbekannte Schlüssel {items}", what=what, items=sorted(unknown)))
        for key in ("title", "description", "category"):
            if key in block and not isinstance(block[key], str):
                raise TemplateError(_t("{what}.{key} muss Text sein", what=what, key=key))
        if "tags" in block and not _is_str_list(block["tags"]):
            raise TemplateError(_t("{what}.tags muss eine Liste von Texten sein", what=what))
        if "sample" in block:
            if not _is_str_dict(block["sample"]):
                raise TemplateError(_t("{what}.sample muss ein Objekt Text->Text sein", what=what))
            unknown_sample = set(block["sample"]) - set(fields)
            if unknown_sample:
                raise TemplateError(_t("{what}.sample verweist auf unbekannte Felder {items}", what=what,
                                       items=sorted(unknown_sample)))
        if "lines" in block:
            lines = layout.get("lines")
            if not _is_str_list(block["lines"]) or not isinstance(lines, list) or len(block["lines"]) != len(lines):
                raise TemplateError(_t("{what}.lines braucht genau so viele Zeilen wie layout.lines", what=what))
        if "texts" in block:
            if not _is_str_dict(block["texts"]):
                raise TemplateError(_t("{what}.texts muss ein Objekt Objekt-ID->Text sein", what=what))
            for obj_id in block["texts"]:
                if obj_id not in objects or "text" not in objects[obj_id]:
                    raise TemplateError(_t("{what}.texts: Textobjekt '{id}' gibt es nicht", what=what, id=obj_id))
        _check_translation_fields(block, fields, what)
    return raw


def localize_data(data: dict, lang: str | None) -> tuple[dict, bool]:
    """Vorlagendaten in der Sprache `lang`: der Block `translations.<lang>` ersetzt Titel,
    Beschreibung, Kategorie, Stichworte, Beispielwerte, Zeilen (`lines`), Texte von
    Dokumentobjekten (`texts`) und je Feld Bezeichnung, Standardwert, Auswahl, Tabelle und
    Auswahl-Beschriftungen. Die ID (`name`) bleibt. Rückgabe: (Daten, Block angewendet)."""
    raw = data.get("translations")
    block = raw.get(lang) if isinstance(raw, dict) and lang else None
    if not isinstance(block, dict) or not block:
        return data, False
    out = json.loads(json.dumps(data))
    for key in ("title", "description", "category", "tags"):
        if key in block:
            out[key] = block[key]
    if "sample" in block and isinstance(out.get("sample", {}), dict):
        out["sample"] = {**out.get("sample", {}), **block["sample"]}
    if "lines" in block and isinstance(out.get("layout"), dict):
        out["layout"]["lines"] = list(block["lines"])
    if "texts" in block and isinstance(out.get("document"), dict):
        for obj in out["document"].get("objects", []):
            if isinstance(obj, dict) and obj.get("id") in block["texts"]:
                obj["text"] = block["texts"][obj["id"]]
    field_block = block.get("fields", {})
    if isinstance(field_block, dict):
        for raw_field in out.get("fields", []):
            entry = field_block.get(raw_field.get("id")) if isinstance(raw_field, dict) else None
            if not isinstance(entry, dict):
                continue
            base_choices = raw_field.get("choices")
            for key in ("label", "default", "map"):
                if key in entry:
                    raw_field[key] = entry[key]
            if "choices" in entry:
                raw_field["choices"] = list(entry["choices"])
                if isinstance(base_choices, list) and "default" not in entry \
                        and raw_field.get("default") in base_choices:
                    # Standardwert an derselben Stelle der übersetzten Auswahl
                    raw_field["default"] = entry["choices"][base_choices.index(raw_field["default"])]
            if "choice_labels" in entry:
                raw_field["choice_labels"] = dict(entry["choice_labels"])
            elif "choices" in entry:
                raw_field.pop("choice_labels", None)
    return out, True


def _alt_maps(data: dict, lang: str | None) -> dict[str, tuple[tuple[str, str], ...]]:
    """Je lookup-Feld die Tabellen der übrigen Sprachen (Basis und Übersetzungen außer `lang`)."""
    raw = data.get("translations") if isinstance(data.get("translations"), dict) else {}
    result: dict[str, tuple[tuple[str, str], ...]] = {}
    for raw_field in data.get("fields", []):
        if not isinstance(raw_field, dict) or raw_field.get("type") != "lookup":
            continue
        fid = raw_field.get("id")
        maps = []
        if isinstance(raw.get(lang), dict):
            maps.append(raw_field.get("map"))
        for other, block in raw.items():
            if other == lang or not isinstance(block, dict):
                continue
            entry = (block.get("fields") or {}).get(fid)
            if isinstance(entry, dict):
                maps.append(entry.get("map"))
        pairs = [(k, v) for m in maps if isinstance(m, dict) for k, v in m.items()
                 if isinstance(k, str) and isinstance(v, str)]
        if pairs:
            result[fid] = tuple(pairs)
    return result


def template_from_dict(data: dict, path: Path | None = None, *, lang: str | None = None) -> Template:
    """Baut eine Vorlage aus `data` in der Sprache `lang` (None: die der Anfrage, `i18n.language()`;
    siehe `localize_data`). Der Übersetzungsblock wird immer geprüft."""
    source = data
    where = _t("Vorlage {value}", value=path.name if path else data.get('name', '?'))
    unknown_top = set(data) - set(TOP_LEVEL_KEYS)
    if unknown_top:
        raise TemplateError(_t("{where}: unbekannte Schlüssel {sorted}", where=where, sorted=sorted(unknown_top)))
    if lang is None:
        lang = i18n.language()
    translations = check_translations(data, where)
    alt_maps = _alt_maps(data, lang)
    data, localized = localize_data(data, lang)
    title_raw = data.get("title", "")
    if not isinstance(title_raw, str):
        raise TemplateError(_t("{where}: title muss Text sein", where=where))

    version = data.get("schema_version")
    if type(version) is not int:
        raise TemplateError(_t("{where}: schema_version fehlt oder ist keine Zahl", where=where))
    if version > SCHEMA_VERSION:
        raise TemplateError(_t("{where}: Schema-Version {version} ist neuer als diese App ({schema_version}), bitte App aktualisieren", where=where, version=version, schema_version=SCHEMA_VERSION))
    min_app = data.get("min_app_version")
    if min_app and _version_tuple(min_app) > _version_tuple(__version__):
        raise TemplateError(_t("{where}: braucht App-Version {min_app}, installiert ist {version}", where=where, min_app=min_app, version=__version__))

    fields, field_ids = _build_fields(data.get("fields", []), where)
    if alt_maps:
        fields = tuple(dataclasses.replace(f, alt_map=alt_maps[f.id]) if f.id in alt_maps else f for f in fields)
    known = field_ids | {f"{f.id}_model" for f in fields if f.clean == "serial"}
    dummy = {name: "X" for name in known}

    has_layout_key = "layout" in data
    layout_raw = data.get("layout", {})
    if not isinstance(layout_raw, dict):
        raise TemplateError(_t("{where}: layout muss ein Objekt sein", where=where))
    layout = dict(layout_raw)
    unknown_layout = set(layout) - _LAYOUT_KEYS
    if unknown_layout:
        raise TemplateError(_t("{where}: unbekannte Layout-Schlüssel {sorted}", where=where, sorted=sorted(unknown_layout)))
    _check_layout(layout, where)
    _check_placeholders(_layout_strings(layout), known, dummy, where)
    layout_nonempty = bool(layout)

    document_raw = data.get("document")
    generator_raw = data.get("generator")

    if document_raw is None and generator_raw is None and not has_layout_key:
        raise TemplateError(_t("{where}: Vorlage braucht layout, document oder generator", where=where))
    if document_raw is not None and generator_raw is not None:
        raise TemplateError(_t("{where}: document und generator schließen sich aus", where=where))
    if document_raw is not None and layout_nonempty:
        raise TemplateError(_t("{where}: document und layout schließen sich aus", where=where))
    if generator_raw is not None and layout_nonempty:
        raise TemplateError(_t("{where}: generator und layout schließen sich aus", where=where))

    document_obj: LabelDocument | None = None
    if document_raw is not None:
        if not isinstance(document_raw, dict):
            raise TemplateError(_t("{where}: document muss ein Objekt sein", where=where))
        try:
            document_obj = document_from_dict(document_raw)
        except DocumentError as exc:
            raise TemplateError(f"{where}: {exc}") from exc
        _check_placeholders(texts(document_obj), known, dummy, where)

    generator_obj: GeneratorRef | None = None
    if generator_raw is not None:
        if not isinstance(generator_raw, dict):
            raise TemplateError(_t("{where}: generator muss ein Objekt sein", where=where))
        unknown_gen = set(generator_raw) - {"name", "params"}
        if unknown_gen:
            raise TemplateError(_t("{where}: unbekannte generator-Schlüssel {sorted}", where=where, sorted=sorted(unknown_gen)))
        gen_name = generator_raw.get("name")
        if gen_name not in GENERATORS:
            raise TemplateError(_t("{where}: Generator '{gen_name}' unbekannt (erlaubt: {items})", where=where, gen_name=gen_name, items=', '.join(GENERATORS)))
        gen_params = generator_raw.get("params", {})
        if not isinstance(gen_params, dict):
            raise TemplateError(_t("{where}: generator.params muss ein Objekt sein", where=where))
        generator_obj = GeneratorRef(name=gen_name, params=dict(gen_params))

    category_raw = data.get("category", "")
    if not isinstance(category_raw, str):
        raise TemplateError(_t("{where}: category muss Text sein", where=where))

    tags_raw = data.get("tags", [])
    if not (isinstance(tags_raw, list) and all(isinstance(t, str) for t in tags_raw)):
        raise TemplateError(_t("{where}: tags muss eine Liste von Texten sein", where=where))

    sample_raw = data.get("sample", {})
    if not (isinstance(sample_raw, dict)
            and all(isinstance(k, str) and isinstance(v, str) for k, v in sample_raw.items())):
        raise TemplateError(_t("{where}: sample muss ein Objekt Text->Text sein", where=where))
    unknown_sample = set(sample_raw) - field_ids
    if unknown_sample:
        raise TemplateError(_t("{where}: sample verweist auf unbekannte Felder {sorted}", where=where, sorted=sorted(unknown_sample)))

    target_raw = data.get("target")
    if target_raw is not None:
        if not isinstance(target_raw, str):
            raise TemplateError(_t("{where}: target muss Text oder null sein", where=where))
        try:
            find_target(target_raw)
        except ValueError as exc:
            raise TemplateError(f"{where}: {exc}") from exc

    shorten_raw = data.get("shorten", [])
    if not isinstance(shorten_raw, list):
        raise TemplateError(_t("{where}: shorten muss eine Liste sein", where=where))
    shorten_rules: list[ShortenRule] = []
    for item in shorten_raw:
        if not isinstance(item, dict):
            raise TemplateError(_t("{where}: shorten-Eintrag muss ein Objekt sein", where=where))
        unknown_shorten = set(item) - {"field", "rule", "n"}
        if unknown_shorten:
            raise TemplateError(_t("{where}: unbekannte shorten-Schlüssel {sorted}", where=where, sorted=sorted(unknown_shorten)))
        sfield = item.get("field")
        if sfield not in field_ids:
            raise TemplateError(_t("{where}: shorten: Feld '{sfield}' gibt es nicht", where=where, sfield=sfield))
        srule = item.get("rule")
        if srule not in RULES:
            raise TemplateError(_t("{where}: shorten: Regel '{srule}' unbekannt (erlaubt: {items})", where=where, srule=srule, items=', '.join(RULES)))
        sn = item.get("n")
        if srule in ("last", "first"):
            if isinstance(sn, bool) or not isinstance(sn, int) or sn <= 0:
                raise TemplateError(_t("{where}: shorten: n muss eine ganze Zahl > 0 sein", where=where))
        elif sn is not None:
            raise TemplateError(_t("{where}: shorten: n ist nur bei 'last'/'first' zulässig", where=where))
        shorten_rules.append(ShortenRule(field=sfield, rule=srule, n=sn))

    tapes_raw = data.get("tapes", [])
    if not (isinstance(tapes_raw, list) and all(isinstance(t, str) for t in tapes_raw)):
        raise TemplateError(_t("{where}: tapes muss eine Liste von Texten sein", where=where))
    try:
        validate_allowed(tapes_raw)
    except ValueError as exc:
        raise TemplateError(f"{where}: {exc}") from exc

    default_copies_raw = data.get("default_copies", 1)
    if (isinstance(default_copies_raw, bool) or not isinstance(default_copies_raw, int)
            or not 1 <= default_copies_raw <= 10):
        raise TemplateError(_t("{where}: default_copies muss eine ganze Zahl 1..10 sein", where=where))

    checks_raw = data.get("checks", {})
    if not isinstance(checks_raw, dict):
        raise TemplateError(_t("{where}: checks muss ein Objekt sein", where=where))
    unknown_checks = set(checks_raw) - {"min_font_mm"}
    if unknown_checks:
        raise TemplateError(_t("{where}: unbekannte checks-Schlüssel {sorted}", where=where, sorted=sorted(unknown_checks)))
    if "min_font_mm" in checks_raw:
        min_font = checks_raw["min_font_mm"]
        if isinstance(min_font, bool) or not isinstance(min_font, (int, float)) or min_font <= 0:
            raise TemplateError(_t("{where}: checks.min_font_mm muss eine Zahl > 0 sein", where=where))

    with i18n.use_language(lang):
        text_size_field, text_height = _text_size_fields(fields, data, layout, document_obj, generator_obj, where)

    return Template(
        name=data.get("name") or (path.name.removesuffix(".tapesmith.json").removesuffix(".p12label.json") if path else "unbenannt"),
        description=data.get("description", ""), fields=fields, layout=layout,
        schema_version=version, min_app_version=min_app, path=path,
        document=document_obj, generator=generator_obj,
        category=category_raw, tags=tuple(tags_raw), sample=dict(sample_raw), target=target_raw,
        shorten=tuple(shorten_rules), tapes=tuple(tapes_raw), default_copies=default_copies_raw,
        checks=dict(checks_raw), text_height=text_height, text_size_field=text_size_field,
        title=title_raw, translations=translations, language=lang, localized=localized, source=source,
    )


def load_template(path: Path) -> Template:
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TemplateError(_t("Vorlage {name} nicht lesbar: {exc}", name=path.name, exc=exc)) from exc
    version = data.get("schema_version")
    if type(version) is int and version < SCHEMA_VERSION:
        backup = path.with_name(f"{path.name}.bak-v{version}")
        backup.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        while version < SCHEMA_VERSION:
            step = MIGRATIONS.get(version)
            if step is None:
                raise TemplateError(_t("Vorlage {name}: keine Migration von Version {version}", name=path.name, version=version))
            data = step(data)
            data["schema_version"] = version + 1
            version += 1
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return template_from_dict(data, path)


def template_to_dict(t: Template) -> dict:
    fields = []
    for f in t.fields:
        raw = {"id": f.id, "label": f.label, "type": f.type}
        if f.default:
            raw["default"] = f.default
        if f.required:
            raw["required"] = True
        if f.secret:
            raw["secret"] = True
        if f.choices:
            raw["choices"] = list(f.choices)
        if f.clean:
            raw["clean"] = f.clean
        if f.format:
            raw["format"] = f.format
        if f.offset_days:
            raw["offset_days"] = f.offset_days
        if f.type == "lookup":
            raw["source"] = f.source
            raw["map"] = dict(f.map)
        if f.base_field:
            raw["base_field"] = f.base_field
        if f.offset_months:
            raw["offset_months"] = f.offset_months
        if f.offset_field:
            raw["offset_field"] = f.offset_field
        if f.offset_months_field:
            raw["offset_months_field"] = f.offset_months_field
        if f.max_len:
            raw["max_len"] = f.max_len
        if f.multiline:
            raw["multiline"] = True
        if f.choice_labels:
            raw["choice_labels"] = dict(f.choice_labels)
        fields.append(raw)

    data = {"schema_version": t.schema_version, "name": t.name, "description": t.description, "fields": fields}
    if t.document is None and t.generator is None:
        data["layout"] = t.layout
    if t.document is not None:
        data["document"] = document_to_dict(t.document)
    if t.generator is not None:
        data["generator"] = {"name": t.generator.name, "params": dict(t.generator.params)}
    if t.category:
        data["category"] = t.category
    if t.tags:
        data["tags"] = list(t.tags)
    if t.sample:
        data["sample"] = dict(t.sample)
    if t.target is not None:
        data["target"] = t.target
    if t.shorten:
        data["shorten"] = [
            {"field": r.field, "rule": r.rule, **({"n": r.n} if r.n is not None else {})} for r in t.shorten
        ]
    if t.tapes:
        data["tapes"] = list(t.tapes)
    if t.default_copies != 1:
        data["default_copies"] = t.default_copies
    if t.checks:
        data["checks"] = dict(t.checks)
    if t.min_app_version:
        data["min_app_version"] = t.min_app_version
    if t.text_height is not None:
        data["text_height"] = t.text_height
    if t.title:
        data["title"] = t.title
    # Eine schon übersetzte Vorlage ist eine Momentaufnahme in dieser Sprache (ohne Übersetzungsblock,
    # der zur geänderten Basis nicht mehr passen würde); sonst bleibt der Block erhalten.
    if t.translations and not t.localized:
        data["translations"] = json.loads(json.dumps(t.translations))
    return data


def template_source_dict(t: Template) -> dict:
    """Daten der Vorlage wie in der Datei (unübersetzt, mit Übersetzungsblock), z. B. für den Export."""
    if t.source is not None:
        return json.loads(json.dumps(t.source))
    return template_to_dict(t)
