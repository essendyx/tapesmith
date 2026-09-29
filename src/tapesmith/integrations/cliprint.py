"""Druckhilfen für CLI-Befehle der Homelab-Integrationen.

Verallgemeinert den Ablauf aus `cli_cmds/disks.py`: Vorlage finden, Zeilen auf die Eingabefelder
der Vorlage kürzen, Serie bauen (Zähler aus dem zentralen Nummernkreis-Ordner), Kontaktabzug,
`--dry-run`, Druck über `emit_labels`, Zähler erst nach echtem Druck. Namespace-Felder werden nur
über `getattr` gelesen, weil viele Befehle nur `add_print_options` registrieren.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path

from tapesmith import numbering
from tapesmith.cli_cmds.base import CliContext, add_print_options, emit_labels
from tapesmith.dataimport.batch import batch_meta, build_batch, commit_counters, contact_sheet
from tapesmith.errors import EXIT_ERROR, EXIT_OK, EXIT_TEMPLATE, EXIT_UNREACHABLE
from tapesmith.integrations.errors import IntegrationError
from tapesmith.sshscan import SshError
from tapesmith.tape.profiles import current_tape
from tapesmith.templates.fill import input_fields
from tapesmith.templates.model import Template, TemplateError
from tapesmith.templates.store import find_template
from tapesmith.i18n import _t

COMPUTED_TYPES = frozenset({"date", "counter", "lookup", "fixed"})


def add_series_options(parser: argparse.ArgumentParser, *, template: str) -> None:
    """Optionen für Seriendruck: --template, --dry-run, --contact-sheet und die Druckoptionen."""
    parser.add_argument("--template", default=template, metavar=_t("NAME|PFAD"),
                        help=_t("Vorlage (Standard: {template})", template=template))
    parser.add_argument("--dry-run", action="store_true",
                        help=_t("nur Zusammenfassung bzw. Kontaktabzug, nicht drucken, keine Zähler"))
    parser.add_argument("--contact-sheet", type=Path, metavar=_t("DATEI.png"), help=_t("Kontaktabzug schreiben"))
    add_print_options(parser)


def filter_inputs(template: Template, values: Mapping[str, str]) -> tuple[dict[str, str], list[str]]:
    """(Werte nur für Eingabefelder, sortierte Liste übergangener berechneter Felder)."""
    allowed = {f.id for f in input_fields(template)}
    computed = {f.id for f in template.fields if f.type in COMPUTED_TYPES}
    kept = {key: value for key, value in values.items() if key in allowed}
    skipped = sorted(key for key in values if key not in allowed and key in computed)
    return kept, skipped


def check_rows(ctx: CliContext, template_name: str, rows: Sequence[Mapping[str, str]]) -> int:
    """Rendert die Zeilen nur zur Prüfung (kein Druck, keine Vorschau, keine Zähler).

    Rückgabe EXIT_OK, wenn jede Zeile ein druckbares Label ergibt, sonst der Exit-Code mit Meldung
    auf stderr. Für Befehle, die vor dem Druck etwas anlegen (z. B. eine Nummer vergeben)."""
    try:
        template = find_template(template_name)
    except TemplateError as exc:
        ctx.err(str(exc))
        return EXIT_TEMPLATE
    filtered = [filter_inputs(template, row)[0] for row in rows]
    cfg = ctx.load_config()
    try:
        plan = build_batch(template, filtered, ctx.load_profile(), now=datetime.now(),
                           counters=numbering.counter_store(cfg), tape=current_tape(cfg))
    except ValueError as exc:
        ctx.err(str(exc))
        return EXIT_ERROR
    for error in plan.errors:
        ctx.err(error)
    if plan.errors or len(plan.labels) != len(rows):
        return EXIT_ERROR
    return EXIT_OK


def print_rows(ctx: CliContext, args: argparse.Namespace, template_name: str,
               rows: Sequence[Mapping[str, str]], *,
               on_printed: Callable[[], None] | None = None) -> int:
    """Druckt Zeilen als Serie über eine Vorlage; Rückgabe Exit-Code (0, 1, 6)."""
    try:
        template = find_template(template_name)
    except TemplateError as exc:
        ctx.err(str(exc))
        return EXIT_TEMPLATE

    labels = {f.id: f.label for f in template.fields}
    filtered: list[dict[str, str]] = []
    hinted: list[str] = []
    for row in rows:
        kept, skipped = filter_inputs(template, row)
        filtered.append(kept)
        for key in skipped:
            if key not in hinted:
                hinted.append(key)
                ctx.err(_t("Hinweis: Feld '{get}' wird von der Vorlage berechnet, übergebener Wert ignoriert", get=labels.get(key, key)))

    cfg = ctx.load_config()
    profile = ctx.load_profile()
    tape = current_tape(cfg)
    counters = numbering.counter_store(cfg)

    try:
        plan = build_batch(template, filtered, profile, now=datetime.now(), counters=counters, tape=tape)
    except ValueError as exc:
        ctx.err(str(exc))
        return EXIT_ERROR

    for error in plan.errors:
        ctx.err(error)

    sheet = getattr(args, "contact_sheet", None)
    if sheet:
        contact_sheet(plan, profile, tape=tape).save(sheet)
        ctx.out(_t("Kontaktabzug: {sheet}", sheet=sheet))

    if getattr(args, "dry_run", False):
        cut_marks = not getattr(args, "no_cut_marks", False)
        ctx.out(plan.summary(profile, chain=bool(getattr(args, "chain", False)), cut_marks=cut_marks))
        return EXIT_OK

    if not plan.labels:
        ctx.err(_t("Keine druckbaren Zeilen"))
        return EXIT_ERROR

    printed = emit_labels(ctx, plan.labels, batch_meta(plan, "cli"))
    if printed:
        commit_counters(plan, counters)
        if on_printed is not None:
            on_printed()
    return EXIT_OK


def print_one(ctx: CliContext, args: argparse.Namespace, template_name: str,
              values: Mapping[str, str], *, on_printed: Callable[[], None] | None = None) -> int:
    """Druckt ein einzelnes Label (`print_rows` mit einer Zeile)."""
    return print_rows(ctx, args, template_name, [values], on_printed=on_printed)


def run_guarded(ctx: CliContext, fn: Callable[[], int]) -> int:
    """Führt `fn` aus und setzt Fehler in Meldung plus Exit-Code um."""
    try:
        return fn()
    except IntegrationError as exc:
        ctx.err(str(exc))
        if exc.hint:
            ctx.err(_t("Hinweis: {hint}", hint=exc.hint))
        return exc.exit_code
    except SshError as exc:
        ctx.err(str(exc))
        return EXIT_UNREACHABLE
    except TemplateError as exc:
        ctx.err(str(exc))
        return EXIT_TEMPLATE
    except KeyError as exc:
        ctx.err(str(exc.args[0]) if exc.args else _t("Unbekannter Schlüssel"))
        return EXIT_ERROR
    except ValueError as exc:
        ctx.err(str(exc))
        return EXIT_ERROR
