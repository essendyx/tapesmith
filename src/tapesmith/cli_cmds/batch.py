"""Plugin-Befehl 'p12 batch': Vorlage über viele Datensätze drucken, aus
CSV/XLSX, Zwischenablage (stdin, siehe `--clipboard`), Zeilenliste oder Serien/Zählern."""

from __future__ import annotations

import argparse
import re
from datetime import datetime
from pathlib import Path

from tapesmith import numbering
from tapesmith.cli_cmds.base import YES_ANSWERS, add_print_options, emit_labels, parse_sets
from tapesmith.dataimport.batch import batch_meta, build_batch, commit_counters, contact_sheet, rows_from_series, rows_from_table
from tapesmith.dataimport.mapping import (
    ColumnMapping,
    MappingStore,
    auto_map,
    filter_rows,
    parse_row_selection,
)
from tapesmith.dataimport.table import load_table, read_clipboard_text, read_lines
from tapesmith.errors import EXIT_ERROR, EXIT_OK, EXIT_TEMPLATE
from tapesmith.tape.profiles import current_tape
from tapesmith.templates.fill import input_fields
from tapesmith.templates.series import MODES, Counter, SeriesSpec
from tapesmith.templates.store import find_template
from tapesmith.i18n import N_, _t

COMMAND = "batch"
HELP = N_("Vorlage über viele Datensätze drucken (Import/Serie)")

_SIMPLE = re.compile(r"^(?P<start>[A-Za-z0-9]+)\.\.(?P<count>\d+)$")
_NESTED = re.compile(r"^(?P<outer>[A-Za-z]+)(?P<inner>\d+)\.\.(?P<ocount>\d+)x(?P<icount>\d+)$")

_EXAMPLE_HINT = N_("Beispiel: port=1..24, box=A1..3x3 (verschachtelt), id=K-{}-X:1..5 (Präfix/Suffix)")


def register(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("template", help=_t("Name oder Pfad einer Vorlage"))
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--data", type=Path, metavar=_t("DATEI"), help=_t("CSV/TSV/XLSX-Datei"))
    src.add_argument("--clipboard", action="store_true",
                     help=_t("Zeilen von stdin lesen, z. B.: Get-Clipboard | p12 batch vorlage --clipboard"))
    src.add_argument("--lines", metavar=_t("DATEI|-"), help=_t("Datei oder '-' (stdin): eine Zeile pro Label"))
    src.add_argument("--series", action="append", default=[], metavar=_t("FELD=SPEZ"),
                     help=_t("Kurzsyntax: port=1..24, box=A1..3x3, id=K-{}-X:1..5; mehrfach für parallele Serien"))
    parser.add_argument("--map", action="append", default=[], metavar=_t("FELD=SPALTE"),
                        help=_t("Spaltenzuordnung überschreiben"))
    parser.add_argument("--save-mapping", action="store_true", help=_t("Zuordnung für diese Vorlage merken"))
    parser.add_argument("--rows", metavar="1-5,8", help=_t("nur diese Zeilen (1-basiert)"))
    parser.add_argument("--filter", default="", metavar="TEXT", help=_t("nur passende Zeilen"))
    parser.add_argument("--filter-column", metavar=_t("SPALTE"), help=_t("Filter nur in dieser Spalte"))
    parser.add_argument("--set", action="append", default=[], metavar=_t("FELD=WERT"),
                        help=_t("fester Wert für alle Zeilen"))
    parser.add_argument("--dry-run", action="store_true",
                        help=_t("nur Zusammenfassung/Kontaktabzug, nicht drucken, keine Zähler"))
    parser.add_argument("--contact-sheet", type=Path, metavar=_t("DATEI.png"), help=_t("Kontaktabzug schreiben"))
    add_print_options(parser)


def parse_series_spec(body: str) -> SeriesSpec:
    """Kurzsyntax einer einzelnen Serie (ohne 'feld='), z. B. '1..24', 'A1..3x3', 'K-{}-X:1..5'."""
    prefix = suffix = ""
    if "{}" in body:
        template, sep, rest = body.partition(":")
        if not sep or "{}" not in template:
            raise ValueError(_t("Serie '{body}' nicht verstanden. {example_hint}", body=body, example_hint=_t(_EXAMPLE_HINT)))
        prefix, _, suffix = template.partition("{}")
        body = rest

    m = _NESTED.match(body)
    if m:
        outer_start = m["outer"].upper()
        inner_start = m["inner"]
        outer_count = int(m["ocount"])
        inner_count = int(m["icount"])
        inner_width = len(inner_start) if inner_start.startswith("0") and len(inner_start) > 1 else 0
        outer = Counter(start=outer_start, kind="letters")
        inner = Counter(start=inner_start, kind="number", width=inner_width)
        return SeriesSpec(mode="nested", counters=(outer, inner), count=outer_count,
                          inner_count=inner_count, prefix=prefix, suffix=suffix)

    m = _SIMPLE.match(body)
    if m:
        start = m["start"]
        count = int(m["count"])
        if start.isalpha():
            counter = Counter(start=start.upper(), kind="letters")
        elif start.isdigit():
            width = len(start) if start.startswith("0") and len(start) > 1 else 0
            counter = Counter(start=start, kind="number", width=width)
        else:
            raise ValueError(_t("Serie '{body}' nicht verstanden. {example_hint}", body=body, example_hint=_t(_EXAMPLE_HINT)))
        return SeriesSpec(mode="simple", counters=(counter,), count=count, prefix=prefix, suffix=suffix)

    raise ValueError(_t("Serie '{body}' nicht verstanden ({items}). {example_hint}", body=body, items=', '.join(MODES), example_hint=_t(_EXAMPLE_HINT)))


def parse_series_arg(text: str) -> tuple[str, SeriesSpec]:
    field, sep, body = text.partition("=")
    if not sep or not field:
        raise ValueError(_t("--series erwartet feld=spezifikation, nicht '{text}'. {example_hint}", text=text, example_hint=_t(_EXAMPLE_HINT)))
    return field.strip(), parse_series_spec(body)


def _confirm_error_rows(ctx, n_err: int) -> bool:
    if not n_err:
        return True
    if getattr(ctx.args, "yes", False):
        return True
    if not ctx.stdin_is_tty():
        ctx.err(_t("{n_err} Zeile(n) fehlerhaft. Rest drucken? Mit --yes bestätigen", n_err=n_err))
        return False
    print(_t("Rückfrage: {n_err} Zeile(n) fehlerhaft. Rest drucken? [j/N] ", n_err=n_err), end="",
         file=ctx.stderr, flush=True)
    answer = ctx.stdin.readline().strip().lower()
    if answer not in YES_ANSWERS:
        ctx.err(_t("Nicht gedruckt"))
        return False
    return True


def _series_rows(args, fixed: dict[str, str]) -> tuple[list[dict[str, str]], str]:
    field_specs: dict[str, SeriesSpec] = {}
    for item in args.series:
        field_id, spec = parse_series_arg(item)
        field_specs[field_id] = spec
    return rows_from_series(field_specs, fixed=fixed), _t("Serie")


def _load_table(args, ctx):
    if args.data:
        return load_table(args.data)
    if args.clipboard:
        return read_clipboard_text(ctx.stdin.read())
    text = ctx.stdin.read() if args.lines == "-" else Path(args.lines).read_text(encoding="utf-8")
    return read_lines(text)


def _table_rows(args, template, fixed: dict[str, str], ctx):
    """Baut die Zeilen aus Datei/Zwischenablage/Liste. Rückgabe (rows, source, exit_code);
    `rows is None` bei Fehler (Rückgabewert dann der passende Exit-Code)."""
    table = _load_table(args, ctx)

    store = MappingStore()
    mapping = store.load(template.name, table.headers)
    if mapping is None:
        mapping = auto_map(table.headers, [(f.id, f.label) for f in input_fields(template)])
    overrides = parse_sets(args.map) if args.map else {}
    if overrides:
        mapping = ColumnMapping(columns={**mapping.columns, **overrides})
    if args.save_mapping:
        store.save(template.name, table.headers, mapping)

    missing = [f.label for f in input_fields(template)
              if f.required and not mapping.columns.get(f.id) and f.id not in fixed]
    if missing:
        ctx.err(_t("Pflichtfeld(er) nicht zugeordnet: ") + ", ".join(missing))
        return None, None, EXIT_TEMPLATE

    total = len(table.rows)
    selected = parse_row_selection(args.rows, total) if args.rows else list(range(total))
    if args.filter:
        allowed = set(filter_rows(table, args.filter, args.filter_column))
        selected = [i for i in selected if i in allowed]

    rows = rows_from_table(table, mapping, selected, fixed=fixed)
    return rows, table.source, EXIT_OK


def run(args: argparse.Namespace, ctx) -> int:
    template = find_template(args.template)
    profile = ctx.load_profile()
    cfg = ctx.load_config()
    tape = current_tape(cfg)
    fixed = parse_sets(args.set)

    if args.series:
        try:
            rows, _source = _series_rows(args, fixed)
        except ValueError as exc:
            ctx.err(str(exc))
            return EXIT_ERROR
    else:
        rows, _source, exit_code = _table_rows(args, template, fixed, ctx)
        if rows is None:
            return exit_code

    counters = numbering.counter_store(cfg)
    try:
        plan = build_batch(template, rows, profile, now=datetime.now(), counters=counters, tape=tape)
    except ValueError as exc:
        ctx.err(str(exc))
        return EXIT_ERROR

    for error in plan.errors:
        ctx.err(error)

    if args.contact_sheet:
        contact_sheet(plan, profile, tape=tape).save(args.contact_sheet)
        ctx.out(_t("Kontaktabzug: {contact_sheet}", contact_sheet=args.contact_sheet))

    cut_marks = not getattr(args, "no_cut_marks", False)
    if args.dry_run:
        ctx.out(plan.summary(profile, chain=args.chain, cut_marks=cut_marks))
        return EXIT_OK

    if not plan.labels:
        ctx.err(_t("Keine druckbaren Zeilen"))
        return EXIT_ERROR

    if plan.errors and not _confirm_error_rows(ctx, len(plan.errors)):
        return EXIT_ERROR

    meta = batch_meta(plan, "cli")
    printed = emit_labels(ctx, plan.labels, meta)
    if printed:
        commit_counters(plan, counters)
    return EXIT_OK
