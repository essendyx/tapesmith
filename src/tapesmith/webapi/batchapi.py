"""Serien-/Tabellenlogik der Web-API: Tabelle laden, Zeilen aus Zuordnung
oder Serie zusammensetzen, Plan bauen und als `BatchPlanJson` aufbereiten.

Reine Logik ohne FastAPI: `routes_templates.py` ruft diese Funktionen aus den `/batch/*`-Routen
auf. Zähler werden hier nie verändert (`resolve_values`/`build_batch` peeken nur); erst der
Aufrufer committet nach erfolgreichem Druck (`dataimport.batch.commit_counters`).
"""

from __future__ import annotations

import base64
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from tapesmith.cli_cmds.batch import parse_series_spec
from tapesmith.dataimport.batch import BatchPlan, build_batch, rows_from_series, rows_from_table
from tapesmith.dataimport.mapping import ColumnMapping, MappingStore, auto_map
from tapesmith.dataimport.table import Table, load_table, read_clipboard_text, read_csv, read_lines
from tapesmith.gui.preview_model import design_image, plan_for_preview
from tapesmith.templates.fill import input_fields
from tapesmith.templates.model import Template
from tapesmith.templates.render import render_meta
from tapesmith.webapi.errors import NotFound
from tapesmith.webapi.previews import png_b64
from tapesmith.i18n import _t

if TYPE_CHECKING:  # pragma: no cover
    from tapesmith.webapi.context import ApiContext

MAX_PREVIEWS = 24


def load_source(ctx: ApiContext, source: Mapping) -> Table | None:
    """Baut eine `Table` aus einer `BatchSourceInput`; `series` -> `None`
    (dafür gibt es keine Tabelle, siehe `build_rows`). Unbekannte Pending-ID -> `NotFound`."""
    kind = source.get("type")
    if kind == "text":
        text = source.get("text", "")
        has_header = source.get("has_header")
        if "\t" in text:
            return read_clipboard_text(text, has_header=has_header)
        return read_csv(text, has_header=has_header)
    if kind == "lines":
        return read_lines(source.get("text", ""))
    if kind == "file":
        name = source.get("name") or "import.csv"
        data = base64.b64decode(source.get("data_b64", ""))
        suffix = Path(name).suffix.lower() or ".csv"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / f"import{suffix}"
            path.write_bytes(data)
            kw: dict = {"has_header": source.get("has_header")}
            if suffix in (".xlsx", ".xlsm"):
                kw["sheet"] = source.get("sheet")
            return load_table(path, **kw)
    if kind == "pending":
        pid = source.get("id")
        pending = ctx.extras.get("pending", {})
        entry = pending.get(pid)
        if entry is None:
            raise NotFound(_t("Vorbereitete Daten '{pid}' nicht gefunden", pid=pid))
        entry_type = entry.get("type")
        if entry_type == "table":
            return Table(headers=tuple(entry.get("headers", ())),
                        rows=tuple(tuple(r) for r in entry.get("rows", ())),
                        source=entry.get("source_name", "Vorbereitet"))
        if entry_type == "lines":
            return read_lines("\n".join(entry.get("lines", ())))
        raise ValueError(_t("Vorbereitete Daten '{pid}' sind keine Tabelle (Art '{entry_type}')", pid=pid, entry_type=entry_type))
    if kind == "series":
        return None
    raise ValueError(_t("Unbekannte Quelle '{kind}'", kind=kind))


def build_rows(ctx: ApiContext, template: Template, source: Mapping, mapping: Mapping[str, str] | None,
              selected: Sequence[int] | None, fixed: Mapping[str, str] | None
              ) -> tuple[list[dict[str, str]], dict[str, str], list[str]]:
    """(Zeilen, verwendete Zuordnung, Kopfzeilen). Bei `series` sind Zuordnung/Kopfzeilen leer."""
    fixed = dict(fixed or {})
    if source.get("type") == "series":
        field_specs = {fid: parse_series_spec(spec) for fid, spec in source.get("fields", {}).items()}
        rows = rows_from_series(field_specs, fixed=fixed)
        count = source.get("count")
        if count is not None:
            rows = rows[:count]
        return rows, {}, []

    table = load_source(ctx, source)
    if table is None:
        raise ValueError(_t("Diese Quelle enthält keine Tabelle"))

    fields = input_fields(template)
    if mapping is not None:
        col_mapping = ColumnMapping(columns=dict(mapping))
    else:
        stored = MappingStore().load(template.name, table.headers)
        col_mapping = stored if stored is not None else auto_map(
            table.headers, [(f.id, f.label) for f in fields])

    if source.get("type") == "lines" and fields and table.headers:
        col_mapping = ColumnMapping(columns={**col_mapping.columns, fields[0].id: table.headers[0]})

    rows = rows_from_table(table, col_mapping, selected, fixed=fixed)
    return rows, dict(col_mapping.columns), list(table.headers)


def plan(ctx: ApiContext, template: Template, rows: Sequence[Mapping[str, str]]) -> BatchPlan:
    """`build_batch` mit Profil/Zählern/Band aus dem Kontext (peekt Zähler, committet nie)."""
    return build_batch(template, rows, ctx.profile(), now=ctx.now(), counters=ctx.counters(), tape=ctx.tape())


def _unique(items) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def plan_json(ctx: ApiContext, batch_plan: BatchPlan, mapping: Mapping[str, str], headers: Sequence[str], *,
             chain: bool, cut_marks: bool = True, max_previews: int = MAX_PREVIEWS) -> dict:
    profile = ctx.profile()
    tape = ctx.tape()
    warnings: list[str] = []
    for row in batch_plan.rows:
        if row.render is not None:
            warnings.extend(row.render.warnings)
    previews = []
    for row in batch_plan.rows:
        if row.render is None:
            continue
        if len(previews) >= max_previews:
            break
        single = plan_for_preview([row.render.result.head], profile)
        image = design_image(single, profile, tape)
        title = render_meta(row.render, kind="template", source="gui").title
        previews.append({"index": row.index, "title": title, "design_png": png_b64(image)})
    return {
        "count": len(batch_plan.labels),
        "summary": batch_plan.summary(profile, chain=chain, cut_marks=cut_marks),
        "mapping": dict(mapping),
        "headers": list(headers),
        "warnings": _unique(warnings),
        "errors": list(batch_plan.errors),
        "previews": previews,
    }
