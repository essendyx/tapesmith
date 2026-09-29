"""Vorlagen-Lint: rendert jede Vorlage mit Beispiel- und Maximaldaten und prüft
Überlauf, zu kleine Schrift, nicht scanbare Codes, Objekte außerhalb, 1-Punkt-Linien.

Zähler werden dabei nie echt hochgezählt (`CounterStore` auf eine temporäre Datei).
"""

from __future__ import annotations

import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from tapesmith.device.profile import DeviceProfile
from tapesmith.document.generators import run_generator
from tapesmith.document.render import render_document
from tapesmith.render.checks import MIN_FONT_SIZE
from tapesmith.render.compose import render_label
from tapesmith.render.textsize import TEXT_SIZE_FIELD
from tapesmith.templates.fill import CounterStore, build_document, build_spec, resolve_values
from tapesmith import i18n
from tapesmith.templates.model import Template, TemplateError, template_from_dict
from tapesmith.templates.render import (apply_text_size_document, apply_text_size_spec, min_font_dots,
                                       text_size_mode)
from tapesmith.i18n import N_, _t

NO_SAMPLE = N_("Keine Beispieldaten (sample), Galerie zeigt Standardwerte")


@dataclass(frozen=True)
class LintIssue:
    template: str
    level: str          # "error" | "warning"
    data: str            # "Beispiel" | "Maximal"
    message: str


def lint_values(template: Template, mode: str) -> dict[str, str]:
    """mode 'sample': Standardwerte der Eingabefelder, überschrieben von template.sample; leere
    Pflichtfelder -> 'Beispiel'. mode 'max': wie sample, aber max_len -> 'W' * max_len, choices ->
    längste Auswahl, clean 'serial' behält den Beispielwert (Parser); ebenso ein Feld, das als
    base_field eines date-Felds dient, behält den Beispielwert (muss lesbares Datum bleiben)."""
    input_ids = {f.id for f in template.fields if f.type == "input"}
    values: dict[str, str] = {}
    for f in template.fields:
        if f.type != "input":
            continue
        value = f.default
        if not value and f.required:
            value = _t("Beispiel")
        values[f.id] = value
    for k, v in template.sample.items():
        if k in input_ids:
            values[k] = v
    if mode == "max":
        base_fields = {f.base_field for f in template.fields if f.type == "date" and f.base_field}
        for f in template.fields:
            if f.type != "input" or f.clean == "serial" or f.id in base_fields or f.id == TEXT_SIZE_FIELD:
                continue
            if f.choices:
                values[f.id] = max(f.choices, key=len)
            elif f.max_len:
                values[f.id] = "W" * f.max_len
    return values


def _describe(issue) -> str:
    return f"{issue.object_id}: {issue.message}" if issue.object_id else issue.message


def _lint_dataset(template: Template, profile: DeviceProfile, mode: str, label: str,
                  now: datetime) -> list[LintIssue]:
    issues: list[LintIssue] = []
    threshold = min_font_dots(template, profile)
    if threshold is None:
        threshold = MIN_FONT_SIZE

    with tempfile.TemporaryDirectory() as tmp:
        counters = CounterStore(Path(tmp) / "counters.json")
        inputs = lint_values(template, mode)
        try:
            resolved = resolve_values(template, inputs, now, counters)
            values = resolved.values
            size_mode = text_size_mode(template, values)

            font_sizes: list[int] = []
            if template.kind == "layout":
                spec = build_spec(template, values)
                result = render_label(spec, profile)
                spec, result, size_warnings = apply_text_size_spec(spec, result, size_mode, profile)
                for warning in size_warnings:
                    issues.append(LintIssue(template.name, "warning", label, warning))
                if result.font_size is not None:
                    font_sizes.append(result.font_size)
                for warning in result.warnings:
                    issues.append(LintIssue(template.name, "warning", label, warning))
            else:
                if template.kind == "document":
                    doc, generator_warnings = apply_text_size_document(
                        build_document(template, values), size_mode, profile)
                else:
                    out = run_generator(template.generator, values, profile)
                    doc = out.document
                    generator_warnings = out.warnings
                dr = render_document(doc, profile)
                for issue in dr.issues:
                    issues.append(LintIssue(template.name, issue.level, label, _describe(issue)))
                for warning in generator_warnings:
                    issues.append(LintIssue(template.name, "warning", label, warning))
                font_sizes.extend(dr.font_sizes.values())
        except (TemplateError, ValueError) as exc:
            issues.append(LintIssue(template.name, "error", label, _t("Überlauf/Fehler: {exc}", exc=exc)))
            return issues

        if font_sizes and min(font_sizes) < threshold:
            issues.append(LintIssue(template.name, "error", label, _t("Schrift zu klein: {min} Punkte", min=min(font_sizes))))
    return issues


def translation_gaps(template: Template, lang: str) -> list[str]:
    """Was der Übersetzungsblock `lang` nicht abdeckt, obwohl die Vorlage es zeigt: Beschreibung,
    Kategorie, Stichworte, Feldbezeichnungen (ohne das implizite Feld Schriftgröße)."""
    source = template.source or {}
    block = (source.get("translations") or {}).get(lang)
    if not isinstance(block, dict):
        return []
    gaps = []
    for key in ("description", "category", "tags"):
        if source.get(key) and key not in block:
            gaps.append(key)
    fields = block.get("fields") or {}
    for raw in source.get("fields", []):
        if not isinstance(raw, dict):
            continue
        entry = fields.get(raw.get("id")) or {}
        if raw.get("label") and "label" not in entry:
            gaps.append(f"fields.{raw.get('id')}.label")
        if raw.get("choice_labels") and "choice_labels" not in entry:
            gaps.append(f"fields.{raw.get('id')}.choice_labels")
    return gaps


def _variants(template: Template) -> list[tuple[str, Template | None, str | None]]:
    """Die Vorlage in den übrigen Sprachen ihres Übersetzungsblocks (und der Basis), jeweils
    (Sprache, Vorlage oder None, Fehlertext)."""
    if template.source is None or not template.translations:
        return []
    done = template.language if template.localized else i18n.FALLBACK
    result = []
    for lang in (i18n.FALLBACK, *template.translations):
        if lang == done:
            continue
        try:
            result.append((lang, template_from_dict(template.source, template.path, lang=lang), None))
        except TemplateError as exc:
            result.append((lang, None, str(exc)))
    return result


def lint_template(template: Template, profile: DeviceProfile, *, now: datetime | None = None) -> list[LintIssue]:
    """Beispiel- und Maximaldaten in der geladenen Sprache und in jeder weiteren Sprache des
    Übersetzungsblocks; dazu Lücken der Übersetzung als Warnung."""
    now = now or datetime.now()
    issues: list[LintIssue] = []
    if not template.sample:
        issues.append(LintIssue(template.name, "warning", "-", _t(NO_SAMPLE)))
    issues.extend(_lint_dataset(template, profile, "sample", _t("Beispiel"), now))
    issues.extend(_lint_dataset(template, profile, "max", _t("Maximal"), now))
    for lang in template.translations:
        gaps = translation_gaps(template, lang)
        if gaps:
            issues.append(LintIssue(template.name, "warning", lang,
                                    _t("Übersetzung {lang} unvollständig: {items}", lang=lang, items=", ".join(gaps))))
    for lang, variant, error in _variants(template):
        if variant is None:
            issues.append(LintIssue(template.name, "error", lang, _t("Übersetzung {lang}: {error}", lang=lang,
                                                                     error=error)))
            continue
        issues.extend(_lint_dataset(variant, profile, "sample", f"{_t('Beispiel')} ({lang})", now))
        issues.extend(_lint_dataset(variant, profile, "max", f"{_t('Maximal')} ({lang})", now))
    return issues


def lint_templates(templates: Sequence[Template], profile: DeviceProfile, *,
                   now: datetime | None = None) -> list[LintIssue]:
    now = now or datetime.now()
    issues: list[LintIssue] = []
    for template in templates:
        issues.extend(lint_template(template, profile, now=now))
    return issues
