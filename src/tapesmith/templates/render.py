"""Ein Einstieg zum Rendern jeder Vorlage (Kurzform, Dokument, Generator) für CLI, GUI,
Nachdruck und Serien.

`render_template` wendet das Zielobjekt (Maximal-/Festlänge) an, kürzt schrittweise nach
den Kürzungsregeln der Vorlage und meldet jede Kürzung sichtbar, prüft die Mindestschrift und
berücksichtigt das eingelegte Band (Invertierung auf dunklem Band, Band-Eignung). Kein Qt, kein argparse.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from tapesmith.device.profile import DeviceProfile
from tapesmith.document.generators import GeneratorOutput, run_generator
from tapesmith.document.model import LabelDocument, TextObject
from tapesmith.document.model import texts as document_texts
from tapesmith.document.render import ObjectIssue, render_document, render_spec, to_render_result
from tapesmith.document.targets import TargetProfile, find_target, shorten_steps
from tapesmith.jobs import JobMeta
from tapesmith.labelmeta import template_meta
from tapesmith.render import textsize
from tapesmith.render.checks import MIN_FONT_SIZE
from tapesmith.render.text import fit_size
from tapesmith.render.compose import LabelSpec, RenderResult
from tapesmith.tape.profiles import TapeProfile
from tapesmith.tape.suitability import suitability_reason
from tapesmith.templates.fill import build_document, build_spec, redact, redact_text
from tapesmith.templates.model import Template, TemplateError
from tapesmith.i18n import _t


@dataclass(frozen=True)
class TemplateRender:
    template: Template
    values: dict[str, str]              # tatsächlich verwendete (ggf. gekürzte) Werte
    result: RenderResult
    document: LabelDocument | None      # bei document/generator
    spec: LabelSpec | None              # bei layout
    shortened: tuple[str, ...]          # Beschreibungen der Kürzungen
    notes: tuple[str, ...]              # Generator-Hinweise + Zielobjekt
    warnings: tuple[str, ...]           # result.warnings + Generator-Warnungen + Mindestschrift
    issues: tuple[ObjectIssue, ...]     # bei Dokumenten (für Editor/Lint), sonst ()
    tape_reason: str | None             # Band-Eignung: Rückfragegrund oder None
    generator: GeneratorOutput | None = None  # nur bei generator-Vorlagen


def min_font_dots(template: Template, profile: DeviceProfile) -> int | None:
    """`checks.min_font_mm * profile.dots_per_mm` (gerundet) oder `None`, wenn nicht gesetzt."""
    min_mm = template.checks.get("min_font_mm")
    if min_mm is None:
        return None
    return round(min_mm * profile.dots_per_mm)


def text_size_mode(template: Template, values: dict[str, str]) -> str | float | None:
    """Gewählte Schriftgröße (AUTO, AUTO_FIELD oder mm) oder None, wenn die Vorlage keine hat.
    Ungültige Werte sind ein Vorlagenfehler (Exit 6)."""
    field = template.text_size_field
    if field is None:
        return None
    raw = values.get(field.id, "")
    if not raw.strip():
        raw = field.default
    try:
        mode = textsize.parse(raw)
    except textsize.TextSizeError as exc:
        raise TemplateError(str(exc)) from exc
    if mode == textsize.AUTO_FIELD and not template.text_size_per_field:
        raise TemplateError(_t("Schriftgröße 'auto-feld' gibt es nur bei Raster-Vorlagen"))
    return mode


def _short(text: str) -> str:
    first = text.split("\n", 1)[0].strip()
    return first if len(first) <= 20 else first[:19] + "…"


def apply_text_size_document(doc: LabelDocument, mode: str | float | None,
                             profile: DeviceProfile) -> tuple[LabelDocument, tuple[str, ...]]:
    """Feste Texthöhe für automatisch eingepasste, waagrechte Textobjekte; passt sie nicht in die
    Box, wird auf die größte passende Größe verkleinert (mit Warnung), nie abgeschnitten."""
    if not isinstance(mode, float):
        return doc, ()
    wanted = textsize.mm_to_font_size(mode, profile.dots_per_mm)
    objects = []
    warnings: list[str] = []
    for obj in doc.objects:
        if isinstance(obj, TextObject) and obj.size is None and not obj.vertical and obj.text.strip():
            cw, ch = (obj.h, obj.w) if obj.rotation in (90, 270) else (obj.w, obj.h)
            try:
                fit = fit_size(obj.text.split("\n"), obj.font, ch, cw)
            except ValueError:
                fit = None
            if fit is not None:
                if fit < wanted:
                    warnings.append(textsize.shrink_warning(
                        _t("Text '{short}'", short=_short(obj.text)), mode, textsize.font_size_to_mm(fit, profile.dots_per_mm)))
                obj = dataclasses.replace(obj, size=min(fit, wanted))
        objects.append(obj)
    return dataclasses.replace(doc, objects=tuple(objects)), tuple(warnings)


def apply_text_size_spec(spec: LabelSpec, result: RenderResult, mode: str | float | None,
                         profile: DeviceProfile, tape: TapeProfile | None = None
                         ) -> tuple[LabelSpec, RenderResult, tuple[str, ...]]:
    """Wie `apply_text_size_document` für Kurzform-Vorlagen: `result` ist der automatisch
    eingepasste Render von `spec`."""
    if not isinstance(mode, float) or result.font_size is None or spec.font_size is not None:
        return spec, result, ()
    wanted = textsize.mm_to_font_size(mode, profile.dots_per_mm)
    if result.font_size < wanted:
        actual = textsize.font_size_to_mm(result.font_size, profile.dots_per_mm)
        return spec, result, (textsize.shrink_warning(_t("das Label"), mode, actual),)
    fixed = dataclasses.replace(spec, font_size=wanted)
    return fixed, render_spec(fixed, profile, tape), ()


def _target_note(target: TargetProfile) -> str:
    if target.fixed_length_mm is not None:
        return _t("Ziel: {name} (fest {fixed_length_mm:.0f} mm)", name=target.name, fixed_length_mm=target.fixed_length_mm)
    return _t("Ziel: {name} (max. {max_length_mm:.0f} mm)", name=target.name, max_length_mm=target.max_length_mm)


def _apply_target_spec(spec: LabelSpec, target: TargetProfile) -> LabelSpec:
    if target.fixed_length_mm is not None:
        return dataclasses.replace(spec, fixed_length_mm=target.fixed_length_mm, max_length_mm=None)
    existing = spec.max_length_mm if spec.max_length_mm is not None else float("inf")
    return dataclasses.replace(spec, max_length_mm=min(existing, target.max_length_mm))


def _apply_target_document(doc: LabelDocument, target: TargetProfile) -> LabelDocument:
    if target.fixed_length_mm is not None:
        return dataclasses.replace(doc, length_mode="fixed", length_mm=target.fixed_length_mm)
    return dataclasses.replace(doc, length_mode="max", length_mm=target.max_length_mm)


@dataclass(frozen=True)
class _Outcome:
    result: RenderResult
    document: LabelDocument | None
    spec: LabelSpec | None
    notes: tuple[str, ...]
    warnings: tuple[str, ...]
    issues: tuple[ObjectIssue, ...]
    generator: GeneratorOutput | None


def _render_document_like(doc: LabelDocument, profile: DeviceProfile, tape: TapeProfile | None,
                          target: TargetProfile | None, *, notes: tuple[str, ...] = (),
                          extra_warnings: tuple[str, ...] = (),
                          generator: GeneratorOutput | None = None) -> _Outcome:
    if target is not None:
        doc = _apply_target_document(doc, target)
    dr = render_document(doc, profile, tape=tape)
    result = to_render_result(dr, profile)
    if generator is not None and doc is not generator.document:
        generator = dataclasses.replace(generator, document=doc)
    return _Outcome(result, doc, None, notes, tuple(result.warnings) + extra_warnings, dr.issues, generator)


def _render_candidate(template: Template, values: dict[str, str], profile: DeviceProfile,
                      tape: TapeProfile | None, target: TargetProfile | None,
                      mode: str | float | None = None) -> _Outcome:
    if template.kind == "layout":
        spec = build_spec(template, values)
        if target is not None:
            spec = _apply_target_spec(spec, target)
        result = render_spec(spec, profile, tape)
        spec, result, size_warnings = apply_text_size_spec(spec, result, mode, profile, tape)
        return _Outcome(result, None, spec, (), tuple(result.warnings) + size_warnings, (), None)

    if template.kind == "document":
        doc = build_document(template, values)
        doc, size_warnings = apply_text_size_document(doc, mode, profile)
        return _render_document_like(doc, profile, tape, target, extra_warnings=size_warnings)

    if mode is not None:
        values = dict(values)
        values[textsize.TEXT_SIZE_FIELD] = mode if isinstance(mode, str) else textsize.format_mm(mode)
    out = run_generator(template.generator, values, profile)
    return _render_document_like(out.document, profile, tape, target, notes=out.notes,
                                 extra_warnings=out.warnings, generator=out)


def render_template(template: Template, values: dict[str, str], profile: DeviceProfile, *,
                    tape: TapeProfile | None = None) -> TemplateRender:
    labels = {f.id: f.label for f in template.fields}
    candidates = shorten_steps(values, template.shorten, labels)
    target = find_target(template.target) if template.target else None
    explicit_min = min_font_dots(template, profile)
    iter_min = explicit_min if explicit_min is not None else (MIN_FONT_SIZE if template.shorten else None)
    mode = text_size_mode(template, values)

    last_error: ValueError | None = None
    last_success: tuple[dict[str, str], tuple[str, ...], _Outcome] | None = None
    chosen: tuple[dict[str, str], tuple[str, ...], _Outcome] | None = None
    for vals, shortened in candidates:
        try:
            outcome = _render_candidate(template, vals, profile, tape, target, mode)
        except ValueError as exc:
            last_error = exc
            continue
        last_success = (vals, shortened, outcome)
        font_size = outcome.result.font_size
        if font_size is None or iter_min is None or font_size >= iter_min:
            chosen = last_success
            break

    if chosen is None:
        chosen = last_success
    if chosen is None:
        raise last_error

    vals, shortened, outcome = chosen
    notes = outcome.notes
    if target is not None:
        notes = notes + (_target_note(target),)

    warnings = list(outcome.warnings)
    font_size = outcome.result.font_size
    if explicit_min is not None and font_size is not None and font_size < explicit_min:
        min_mm = template.checks["min_font_mm"]
        warnings.append(
            _t("Schrift {value:.1f} mm unter {min_mm:.1f} mm, für diese Vorlage zu klein", value=font_size / profile.dots_per_mm, min_mm=min_mm))

    tape_reason = suitability_reason(template.name, tape, template.tapes) if tape is not None else None

    return TemplateRender(
        template=template, values=vals, result=outcome.result, document=outcome.document,
        spec=outcome.spec, shortened=shortened, notes=notes, warnings=tuple(warnings),
        issues=outcome.issues, tape_reason=tape_reason, generator=outcome.generator,
    )


def render_meta(tr: TemplateRender, *, kind: str = "template", title_prefix: str = "",
                source: str = "cli") -> JobMeta:
    if tr.template.kind == "layout":
        return template_meta(tr.template, tr.values, tr.spec, kind=kind,
                             title_prefix=title_prefix, source=source)
    # Titel aus den sichtbaren Textobjekten; Icon-Namen und QR-Inhalte gehören nicht hinein
    # (sonst „tabler:milk Earl Grey“ oder doppelte Angaben). Ohne Textobjekt: alle Inhalte.
    texte = [o.text for o in tr.document.objects if o.kind == "text" and o.text] or document_texts(tr.document)
    sensitive = any(f.secret for f in tr.template.fields)
    title = title_prefix + redact_text(" ".join(t for t in texte if t), tr.template, tr.values)
    return JobMeta(source=source, kind=kind, template=tr.template.name, title=title,
                  values=redact(tr.template, tr.values), sensitive=sensitive, spec=None)
