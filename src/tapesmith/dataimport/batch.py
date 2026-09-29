"""Serienauftrag: viele Datensätze durch eine Vorlage schicken.

Baut aus einer Tabelle (Import) oder aus Serien/Zählern (`templates.series`) je Zeile
Eingaben, rendert sie über `templates.render.render_template` und sammelt fehlerfreie Labels
als druckbare `PrintLabel`s. Reine Logik ohne Qt: CLI (`cli_cmds/batch.py`) und GUI
(`gui/batch_dialog.py`) bauen beide auf diesem Modul auf.

Zähler zählen erst nach `commit_counters` (nach erfolgreichem Druck) weiter. Ein Trockenlauf
oder eine bloße Vorschau darf `CounterStore.peek` beliebig oft aufrufen, ohne `counters.json`
zu verändern.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from PIL import Image, ImageDraw

from tapesmith.dataimport.mapping import ColumnMapping, apply_mapping
from tapesmith.dataimport.table import Table
from tapesmith.device.profile import DeviceProfile
from tapesmith.jobs import JobMeta
from tapesmith.pipeline import PrintLabel
from tapesmith.render.chain import plan_chain, plan_single
from tapesmith.render.fonts import load_font
from tapesmith.tape.preview import colorize
from tapesmith.tape.profiles import TapeProfile
from tapesmith.templates.fill import CounterStore, input_fields, resolve_values
from tapesmith.templates.model import Template
from tapesmith.templates.render import TemplateRender, render_meta, render_template
from tapesmith.templates.series import SeriesSpec, parallel_values, series_values
from tapesmith.i18n import _t

MAX_BATCH = 500

_ROW_SPACING = 8      # px zwischen den Zeilen des Kontaktabzugs
_ROW_MARGIN = 4        # px Rand links/rechts und zwischen Nummer und Bild
_ERROR_COLOR = (200, 0, 0)
_TEXT_COLOR = (0, 0, 0)
_BACKGROUND = (255, 255, 255)


@dataclass(frozen=True)
class BatchRow:
    index: int                      # 0-basiert in der Eingabeliste
    inputs: dict[str, str]           # Eingaben für die Vorlage (nach Zuordnung/Serie + feste Werte)
    render: TemplateRender | None = None
    error: str | None = None


@dataclass(frozen=True)
class BatchPlan:
    template: Template
    rows: tuple[BatchRow, ...]
    labels: tuple[PrintLabel, ...]       # nur fehlerfreie Zeilen, Reihenfolge wie rows
    counter_keys: tuple[str, ...]        # ein Eintrag je Zähler-Feld je erfolgreichem Label
    errors: tuple[str, ...]              # "Zeile 3: Feld 'SN' fehlt"

    def summary(self, profile: DeviceProfile, *, chain: bool, cut_marks: bool = True) -> str:
        n = len(self.rows)
        n_err = len(self.errors)
        err_part = _t(" ({n_err} Fehler)", n_err=n_err) if n_err else ""
        heads = [label.head for label in self.labels]
        if not heads:
            return _t("{n} Labels{err_part} · keine druckbaren Zeilen", n=n, err_part=err_part)
        if chain:
            chain_plan = plan_chain(heads, profile, cut_marks=cut_marks)
            single_plan = plan_single(heads, profile)
            band = (_t("ca. {chain_mm:.0f} mm Band als Kette (statt {chain_mm2:.0f} mm einzeln)", chain_mm=chain_plan.balance.chain_mm, chain_mm2=single_plan.balance.chain_mm))
        else:
            single_plan = plan_single(heads, profile)
            band = _t("ca. {chain_mm:.0f} mm Band einzeln", chain_mm=single_plan.balance.chain_mm)
        return f"{n} Labels{err_part} · {band}"


def rows_from_table(table: Table, mapping: ColumnMapping, selected: Sequence[int] | None = None,
                    fixed: Mapping[str, str] | None = None) -> list[dict[str, str]]:
    mapped = apply_mapping(table, mapping, selected)
    fixed = dict(fixed or {})
    return [{**fixed, **row} for row in mapped]


def rows_from_series(field_specs: Mapping[str, SeriesSpec],
                     fixed: Mapping[str, str] | None = None) -> list[dict[str, str]]:
    fixed = dict(fixed or {})
    if not field_specs:
        raise ValueError(_t("Mindestens eine Serie angeben"))
    if len(field_specs) == 1:
        (name, spec), = field_specs.items()
        values = series_values(spec)
        return [{**fixed, name: v} for v in values]
    first_spec = next(iter(field_specs.values()))
    count = len(series_values(first_spec))
    rows = parallel_values(field_specs, count)
    return [{**fixed, **row} for row in rows]


def build_batch(template: Template, rows: Sequence[Mapping[str, str]], profile: DeviceProfile, *,
                now: datetime, counters: CounterStore, tape: TapeProfile | None = None) -> BatchPlan:
    if len(rows) > MAX_BATCH:
        raise ValueError(_t("Zu viele Zeilen ({count} > {max_batch})", count=len(rows), max_batch=MAX_BATCH))

    allowed = {f.id for f in input_fields(template)}
    batch_rows: list[BatchRow] = []
    labels: list[PrintLabel] = []
    counter_keys: list[str] = []
    errors: list[str] = []

    for i, raw in enumerate(rows):
        inputs = {k: v for k, v in raw.items() if k in allowed}
        try:
            resolved = resolve_values(template, inputs, now, counters, counter_offset=len(labels))
            tr = render_template(template, resolved.values, profile, tape=tape)
        except ValueError as exc:
            error = _t("Zeile {value}: {exc}", value=i + 1, exc=exc)
            batch_rows.append(BatchRow(index=i, inputs=inputs, render=None, error=error))
            errors.append(error)
            continue
        batch_rows.append(BatchRow(index=i, inputs=inputs, render=tr, error=None))
        labels.append(PrintLabel(head=tr.result.head, landscape=tr.result.landscape))
        counter_keys.extend(resolved.counter_keys)

    return BatchPlan(template=template, rows=tuple(batch_rows), labels=tuple(labels),
                     counter_keys=tuple(counter_keys), errors=tuple(errors))


def commit_counters(plan: BatchPlan, counters: CounterStore) -> None:
    for key in plan.counter_keys:
        counters.commit(key)


def contact_sheet(plan: BatchPlan, profile: DeviceProfile, *, tape: TapeProfile | None = None,
                  scale: int = 2, max_rows: int = 200) -> Image.Image:
    font = load_font("sans", 14)
    rows = plan.rows[:max_rows]

    pieces: list[tuple[str, tuple[int, int, int], Image.Image | None]] = []
    for row in rows:
        number = f"{row.index + 1}."
        if row.error is not None:
            pieces.append((_t("{number} Fehler: {error}", number=number, error=row.error), _ERROR_COLOR, None))
            continue
        landscape = row.render.result.head.rotate(90, expand=True)
        colored = colorize(landscape, tape)
        if scale != 1:
            colored = colored.resize((colored.width * scale, colored.height * scale), Image.NEAREST)
        pieces.append((number, _TEXT_COLOR, colored))

    dummy = Image.new("RGB", (1, 1))
    measure = ImageDraw.Draw(dummy)
    text_widths = []
    row_heights = []
    for text, _color, image in pieces:
        bbox = measure.textbbox((0, 0), text, font=font)
        text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        text_widths.append(text_w)
        img_h = image.height if image is not None else 0
        row_heights.append(max(text_h, img_h))

    text_col_width = max(text_widths, default=0)
    img_col_width = max((img.width for _kind, _c, img in pieces if img is not None), default=0)
    width = _ROW_MARGIN + text_col_width + (_ROW_MARGIN + img_col_width if img_col_width else 0) + _ROW_MARGIN
    height = sum(row_heights) + _ROW_SPACING * max(len(pieces) - 1, 0) + 2 * _ROW_MARGIN
    height = max(height, 1)
    width = max(width, 1)

    sheet = Image.new("RGB", (width, height), _BACKGROUND)
    draw = ImageDraw.Draw(sheet)
    y = _ROW_MARGIN
    for (text, color, image), row_h in zip(pieces, row_heights):
        text_y = y + (row_h - (measure.textbbox((0, 0), text, font=font)[3])) // 2
        draw.text((_ROW_MARGIN, max(y, text_y)), text, fill=color, font=font)
        if image is not None:
            sheet.paste(image, (_ROW_MARGIN + text_col_width + _ROW_MARGIN, y))
        y += row_h + _ROW_SPACING

    return sheet


def batch_meta(plan: BatchPlan, source: str) -> JobMeta:
    if not plan.labels:
        return JobMeta(source=source, kind="template", template=plan.template.name,
                       title=_t("Serie (0): {name}", name=plan.template.name), values={}, sensitive=False, spec=None)
    first = next(row.render for row in plan.rows if row.render is not None)
    return render_meta(first, kind="template", title_prefix=_t("Serie ({count}): ", count=len(plan.labels)), source=source)
