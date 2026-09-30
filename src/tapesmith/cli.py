"""Kommandozeile 'p12' für Druck, Diagnose, Kalibrierung und Testreihe."""

import argparse
import contextlib
import dataclasses
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from tapesmith import config, modules, numbering, paths
from tapesmith.calibrate import edge_test_head, ruler_content
from tapesmith.cli_cmds import base as cmd_base
from tapesmith.cli_cmds.base import (
    CliContext,
    add_fix_option,
    add_print_options,
    discover_commands,
    parse_sets,
)
from tapesmith.device.profile import load_profile
from tapesmith.document.render import render_spec
from tapesmith.doctor import Check, decoder_check, format_checks, run_checks
from tapesmith.errors import explain, format_advice
from tapesmith.fileutil import FileLockTimeout
from tapesmith.imageinput import load_image_head
from tapesmith.ipc.codec import RemoteError
from tapesmith.ipc.launcher import daemon_pid, daemon_running
from tapesmith.jobs import JobMeta, spec_to_dict
from tapesmith.lock import PrinterBusy
from tapesmith.pipeline import PrintLabel, labels_from_result
from tapesmith.printer import PrinterSession
from tapesmith.protocol.raster import place_on_head
from tapesmith.protocol.status import decode
from tapesmith.render.compose import LabelSpec, render_label
from tapesmith.render.fonts import FontMissing
from tapesmith.tape.profiles import current_tape
from tapesmith.templates.fill import REDACTED, form_fields, resolve_values
from tapesmith.templates.lint import LintIssue, lint_templates
from tapesmith.templates.model import SCHEMA_VERSION, TemplateError, template_from_dict
from tapesmith.templates.render import render_meta, render_template
from tapesmith.templates.store import find_template, list_templates, user_template_files
from tapesmith.transport.base import HexLogTransport, Transport, TransportError
from tapesmith.transport.btports import find_outgoing_port, list_bt_ports
from tapesmith.transport.resolve import open_transport
from tapesmith.transport.usb import usb_check
from tapesmith.verify import Verifier
from tapesmith.i18n import N_, _t

SLEEP = time.sleep
EXIT_OK, EXIT_ERROR, EXIT_UNREACHABLE, EXIT_TEMPLATE, EXIT_BUSY = 0, 1, 5, 6, 7

HANDLED_ERRORS = (KeyboardInterrupt, EOFError, PrinterBusy, FileLockTimeout, TransportError,
                  TemplateError, FontMissing, ValueError, OSError)


def _parser(plugins: dict | None = None) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tapesmith", description=_t("Phomemo P12 Labeldrucker"))
    p.add_argument("--transport", help=_t("auto | COMn | file:pfad (Default aus config.json)"))
    p.add_argument("--hexlog", type=Path, help=_t("alle Bytes mit Zeitstempel in diese Datei schreiben"))
    p.add_argument("--no-daemon", action="store_true",
                   help=_t("ohne Druckdienst p12d direkt drucken (Default: über den Dienst, falls aktiviert)"))
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ports", help=_t("Bluetooth-COM-Ports auflisten"))
    d = sub.add_parser("doctor", help=_t("Selbstdiagnose"))
    d.add_argument("--json", action="store_true")
    d.add_argument("--no-connect", action="store_true", help=_t("Drucker nicht ansprechen"))
    pi = sub.add_parser("print-image", help=_t("PNG/PBM drucken (Breite 96 oder bis Inhaltsbreite)"))
    pi.add_argument("file", type=Path)
    add_print_options(pi)
    c = sub.add_parser("calibrate", help=_t("Kalibrier-Label drucken"))
    c.add_argument("kind", choices=["edge", "ruler"])
    c.add_argument("--length-mm", type=int, default=100)
    pr = sub.add_parser("probe", help=_t("Rohabfragen senden, z. B. 1f1108"))
    pr.add_argument("commands", nargs="+")
    sub.add_parser("verify", help=_t("geführte Testreihe am Drucker"))
    t = sub.add_parser("text", help=_t("Textlabel mit Auto-Fit drucken"))
    t.add_argument("lines", nargs="+", help=_t("eine Zeile pro Argument"))
    t.add_argument("--font", default="sans", choices=["sans", "sans-bold", "mono"])
    t.add_argument("--align", default="left", choices=["left", "center", "right"])
    t.add_argument("--size", type=int, help=_t("feste Schriftgröße statt Auto-Fit"))
    length_group = t.add_mutually_exclusive_group()
    length_group.add_argument("--max-mm", type=float, help=_t("maximale Labellänge in mm"))
    length_group.add_argument("--length-mm", type=float, help=_t("feste Labellänge in mm"))
    t.add_argument("--qr", help=_t("QR-Inhalt links neben dem Text"))
    add_fix_option(t)
    add_print_options(t)
    tp = sub.add_parser("template", help=_t("Vorlagen auflisten, anzeigen, drucken"))
    tsub = tp.add_subparsers(dest="template_cmd", required=True)
    tsub.add_parser("list", help=_t("alle Vorlagen"))
    ts = tsub.add_parser("show", help=_t("Felder einer Vorlage"))
    ts.add_argument("name")
    tpp = tsub.add_parser("print", help=_t("Vorlage füllen und drucken"))
    tpp.add_argument("name", help=_t("Name oder Pfad einer .tapesmith.json"))
    tpp.add_argument("--set", action="append", default=[], metavar=_t("FELD=WERT"))
    add_print_options(tpp)
    tpp.set_defaults(copies=None)  # "nicht angegeben" -> template.default_copies
    tl = tsub.add_parser("lint", help=_t("alle Vorlagen mit Beispiel-/Maximaldaten prüfen"))
    tl.add_argument("names", nargs="*", help=_t("einzelne Vorlagen (Default: alle)"))
    tl.add_argument("--all", action="store_true", help=_t("ausdrücklich alle Vorlagen (wie ohne Angabe)"))
    tl.add_argument("--dir", type=Path, metavar=_t("ORDNER"), help=_t("alle *.tapesmith.json dieses Ordners prüfen"))
    tl.add_argument("--strict", action="store_true", help=_t("auch bei reinen Warnungen Exit 6"))
    tl.add_argument("--json", action="store_true", help=_t("Befunde als JSON ausgeben"))

    for cmd, mod in (plugins or {}).items():
        if cmd in sub.choices:
            raise RuntimeError(_t("Befehl '{cmd}' ist bereits fest eingebaut", cmd=cmd))
        plugin_parser = sub.add_parser(cmd, help=_t(mod.HELP))
        mod.register(plugin_parser)
    return p


def _open(args, cfg, profile, spec: str | None = None) -> Transport:
    """Öffnet den Transport mit hartem Verbindungs-Timeout aus config.json. Das Hex-Log
    dekodiert Statusantworten mit den Codes des Geräts (beim P12 ist der Deckelcode invertiert)."""
    transport = open_transport(spec or args.transport or cfg["transport"], cfg["mac"], None,
                               open_timeout=float(cfg["connect_timeout_s"]),
                               experimental=frozenset(profile.experimental))
    if args.hexlog:
        transport = HexLogTransport(transport, args.hexlog, codes=profile.status_map())
    return transport


def _session(args, cfg, profile) -> PrinterSession:
    return PrinterSession(_open(args, cfg, profile), profile, sleep=SLEEP)


_parse_sets = parse_sets


def _run(args) -> int:
    if args.cmd == "ports":
        for p in list_bt_ports():
            print(f"{p.port}  {p.mac}  {'ausgehend' if p.outgoing else 'eingehend'}")
        return EXIT_OK

    if args.cmd == "doctor":
        try:
            cfg = config.load_config()
        except Exception as exc:
            checks = [Check(_t("Konfiguration"), False, str(exc), _t("config.json prüfen: {config_path}", config_path=paths.config_path()))]
            print(format_checks(checks, as_json=args.json))
            return EXIT_ERROR

        def port_finder(mac):
            if args.transport and args.transport != "auto":
                return args.transport
            return find_outgoing_port(mac)

        def connect(port):
            profile = load_profile(calibration_path=paths.calibration_path())
            with PrinterSession(_open(args, cfg, profile, port), profile, sleep=SLEEP) as s:
                return s.handshake()

        checks = run_checks(cfg["mac"], port_finder, None if args.no_connect else connect,
                            extra_checks=[usb_check, daemon_check, decoder_check])
        print(format_checks(checks, as_json=args.json))
        return EXIT_OK if all(c.ok for c in checks) else EXIT_ERROR

    if args.cmd == "template" and args.template_cmd == "list":
        try:
            hidden = modules.hidden_templates(config.load_config())
        except Exception:  # noqa: BLE001 (kaputte Konfiguration: alle Vorlagen zeigen)
            hidden = frozenset()
        for t in list_templates():
            if t.name in hidden:
                continue
            print(f"{t.name:24} {t.category:12} {t.description}")
        return EXIT_OK
    if args.cmd == "template" and args.template_cmd == "show":
        t = find_template(args.name)
        print(f"{t.name}: {t.description}")
        print(_t("  Kategorie: {value}", value=t.category or '-'))
        print(_t("  Art: {kind}", kind=t.kind))
        print(_t("  Ziel: {value}", value=t.target or '-'))
        print(_t("  Bänder: {value}", value=', '.join(t.tapes) if t.tapes else 'alle'))
        print(_t("  Kopien: {default_copies}", default_copies=t.default_copies))
        for f in form_fields(t):
            flags = ", ".join(x for x in (f.type, _t("Pflicht") if f.required else "", _t("sensibel") if f.secret else "") if x)
            default = f" = {REDACTED if f.secret else f.default}" if f.default else ""
            print(f"  {f.id:12} {f.label} ({flags}){default}")
            if f is t.text_size_field:
                print(_t("  {value:12} Werte: {items} (Zahl = Texthöhe in mm)", value='', items=', '.join(f.choices)))
        return EXIT_OK
    if args.cmd == "template" and args.template_cmd == "lint":
        profile = load_profile(calibration_path=paths.calibration_path())
        if args.dir:
            entries = user_template_files(args.dir)
            templates = []
            issues: list[LintIssue] = []
            for entry in entries:
                try:
                    data = json.loads(entry.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    issues.append(LintIssue(entry.name, "error", "-", _t("nicht lesbar: {exc}", exc=exc)))
                    continue
                version = data.get("schema_version")
                if isinstance(version, int) and version < SCHEMA_VERSION:
                    issues.append(LintIssue(entry.stem, "warning", "-",
                                            _t("Schema {version}, wird beim Laden migriert", version=version)))
                try:
                    templates.append(template_from_dict(data, path=entry))
                except TemplateError as exc:
                    issues.append(LintIssue(entry.name, "error", "-", str(exc)))
            total = len(entries)
        else:
            templates = [find_template(n) for n in args.names] if args.names else list_templates()
            issues = []
            total = len(templates)
        issues.extend(lint_templates(templates, profile))

        if args.json:
            print(json.dumps([dataclasses.asdict(i) for i in issues], ensure_ascii=False))
        else:
            for i in issues:
                print(f"{i.template}: {i.level} ({i.data}): {i.message}")
            errors = sum(1 for i in issues if i.level == "error")
            warnings = sum(1 for i in issues if i.level == "warning")
            print(_t("{total} Vorlagen geprüft, {errors} Fehler, {warnings} Warnungen", total=total, errors=errors, warnings=warnings))
        errors = sum(1 for i in issues if i.level == "error")
        warnings = sum(1 for i in issues if i.level == "warning")
        if errors or (args.strict and warnings):
            return EXIT_TEMPLATE
        return EXIT_OK

    ctx = make_context(args)
    cfg = ctx.load_config()
    profile = ctx.load_profile()

    if args.cmd == "print-image":
        head = load_image_head(args.file, profile, rotate="none")
        cmd_base.emit_labels(ctx, (PrintLabel(head),), JobMeta(kind="image", title=args.file.name))
        return EXIT_OK
    if args.cmd == "calibrate":
        head = (edge_test_head(profile) if args.kind == "edge"
                else place_on_head(ruler_content(profile, args.length_mm), profile))
        # Das Lineal (bis 150 mm) darf nicht nachfragen.
        cmd_base.emit_labels(ctx, (PrintLabel(head),),
                             JobMeta(kind="calibrate", title=_t("Kalibrierung {kind}", kind=args.kind)), confirmed=True)
        return EXIT_OK
    if args.cmd == "probe":
        codes = profile.status_map()
        with _session(args, cfg, profile) as s:
            for cmd in args.commands:
                raw = s.query(cmd)
                texts = ", ".join(m.text for m in decode(raw, codes)) or _t("keine Antwort")
                print(f"{cmd}: {raw.hex() or '-'}  {texts}")
        return EXIT_OK
    if args.cmd == "verify":
        verifier = Verifier(lambda prof: _session(args, cfg, prof), profile, paths.calibration_path())
        try:
            verifier.run()
        finally:
            report = verifier.report
            paths.capabilities_path().write_text(report.to_json(), encoding="utf-8")
            label = _t("Bericht") if report.complete else _t("Bericht (unvollständig)")
            print(f"{label}: {paths.capabilities_path()}")
        return EXIT_OK
    if args.cmd == "text":
        if len(args.lines) > 3:
            raise ValueError(_t("höchstens 3 Zeilen erlaubt, {count} angegeben", count=len(args.lines)))
        spec = LabelSpec(lines=tuple(args.lines), font=args.font, align=args.align, font_size=args.size,
                         max_length_mm=args.max_mm, fixed_length_mm=args.length_mm, qr=args.qr)
        if spec.qr:
            tape = current_tape(cfg)
            render = lambda s, p: render_spec(s, p, tape)  # noqa: E731
        else:
            # render=render_label: Modulattribut, damit Tests es ersetzen können
            render = render_label
        spec, result = cmd_base.render_with_fixes(ctx, spec, profile, args.fix, render=render)
        meta = JobMeta(kind="text", title=" ".join(spec.lines), spec=spec_to_dict(spec))
        cmd_base.emit_labels(ctx, labels_from_result(result), meta, result)
        return EXIT_OK
    if args.cmd == "template" and args.template_cmd == "print":
        template = find_template(args.name)
        if args.hexlog and any(f.secret for f in template.fields):
            print(_t("Warnung: Hex-Log enthält Rasterdaten mit sensiblen Werten"), file=sys.stderr)
        counters = numbering.counter_store(cfg)
        resolved = resolve_values(template, parse_sets(args.set), datetime.now(), counters)
        tape = current_tape(cfg)
        tr = render_template(template, resolved.values, profile, tape=tape)
        for shortened in tr.shortened:
            print(_t("Gekürzt: {shortened}", shortened=shortened), file=sys.stderr)
        for note in tr.notes:
            print(_t("Hinweis: {note}", note=note), file=sys.stderr)
        # result.warnings gibt emit_labels aus; die übrigen (Generator, Schriftgröße, Mindestschrift) hier.
        for warning in tr.warnings:
            if warning not in tr.result.warnings:
                print(_t("Warnung: {warning}", warning=warning), file=sys.stderr)
        # Rückfrage des Fehldruckschutzes nur vor echtem Druck; eine Vorschau blockiert sie nie.
        if tr.tape_reason is not None and not args.yes and not args.preview:
            cmd_base._ask_confirmation(ctx, (tr.tape_reason,))
        meta = render_meta(tr)
        copies = args.copies if args.copies is not None else template.default_copies
        if cmd_base.emit_labels(ctx, labels_from_result(tr.result), meta, tr.result, copies=copies):
            for key in resolved.counter_keys:
                counters.commit(key)
        return EXIT_OK
    raise ValueError(_t("Unbekannter Befehl '{cmd}'", cmd=args.cmd))


def make_context(args: argparse.Namespace) -> CliContext:
    """Baut den Plugin-Kontext: load_config/load_profile lazy und je Aufruf gecacht."""
    cache: dict = {}

    def load_config() -> dict:
        if "cfg" not in cache:
            cache["cfg"] = config.load_config()
        return cache["cfg"]

    def load_profile_cached():
        if "profile" not in cache:
            cache["profile"] = load_profile(calibration_path=paths.calibration_path())
        return cache["profile"]

    def open_session(profile):
        return _session(args, load_config(), profile)

    ctx = CliContext(
        args=args,
        load_config=load_config,
        load_profile=load_profile_cached,
        open_session=open_session,
        emit_label=None,
        emit_head=None,
        stdin=sys.stdin,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )
    ctx.emit_label = lambda result, meta: cmd_base.default_emit_label(ctx, result, meta)
    ctx.emit_head = lambda head, meta: cmd_base.default_emit_head(ctx, head, meta)
    return ctx


def format_error(exc: BaseException) -> str:
    """Klartext mit Handlungsanweisung; allgemeine Fehler ohne doppelten Titel."""
    advice = explain(exc)
    if advice.title == _t("Fehler") and not advice.hint:
        return _t("Fehler: {exc}", exc=exc)
    return format_advice(exc, advice)


def daemon_check() -> Check:
    """Doctor-Zeile zum Druckdienst: nur Information, immer ok."""
    if os.environ.get("TAPESMITH_NO_DAEMON") == "1":
        return Check(_t("Druckdienst"), True, _t("abgeschaltet (TAPESMITH_NO_DAEMON=1), CLI druckt direkt"))
    pid = daemon_pid()
    if pid is None:
        return Check(_t("Druckdienst"), True, _t("läuft nicht, startet bei Bedarf"))
    return Check(_t("Druckdienst"), True, _t("läuft (PID {pid})", pid=pid))


# Befehle, die den Drucker exklusiv brauchen: läuft der Druckdienst, gibt er ihn per Reservierung frei.
EXCLUSIVE_COMMANDS = frozenset({"doctor", "probe", "verify", "setup", "raw", "density"})
LEASE_NOTE = N_("Druckdienst gibt den Drucker für diesen Befehl frei …")


def _needs_lease(args) -> bool:
    if args.cmd not in EXCLUSIVE_COMMANDS:
        return False
    if args.cmd == "doctor" and getattr(args, "no_connect", False):
        return False
    if getattr(args, "no_daemon", False) or os.environ.get("TAPESMITH_NO_DAEMON") == "1":
        return False
    try:
        cfg = config.load_config()
    except Exception:  # noqa: BLE001 (der Befehl selbst meldet die kaputte Konfiguration)
        return False
    spec_explicit = args.transport
    if spec_explicit and str(spec_explicit).lower().startswith("file:"):
        if str(spec_explicit) != str(cfg.get("transport") or ""):
            return False     # eigener Trockenlauf, berührt den Drucker des Dienstes nicht
        # sonst: derselbe file:-Transport wie der Dienst -> weiter zur Reservierung
    return daemon_running()


def _lease_backend(args):
    if cmd_base.BACKEND_FACTORY is not None:
        return cmd_base.BACKEND_FACTORY(make_context(args), None)
    from tapesmith.config import setting
    from tapesmith.ipc.backend import DaemonBackend, local_planner
    from tapesmith.ipc.client import DaemonClient

    cfg = config.load_config()
    profile = load_profile(calibration_path=paths.calibration_path())
    client = DaemonClient.connect(client="cli", timeout_s=float(setting(cfg, "daemon.connect_timeout_s")))
    return DaemonBackend(client, planner=local_planner(cfg, profile))


@contextlib.contextmanager
def exclusive_access(args):
    """Für exklusive Befehle (EXCLUSIVE_COMMANDS) den Drucker beim laufenden Dienst reservieren,
    auch bei ausdrücklichem `--transport COMn`, denn der Dienst hält denselben Drucker."""
    if not _needs_lease(args):
        yield
        return
    print(_t(LEASE_NOTE), file=sys.stderr)
    backend = _lease_backend(args)
    try:
        with backend.lease():
            yield
    finally:
        backend.close()


def module_check(args) -> str | None:
    """Klartext, wenn der Befehl zu einem ausgeschalteten Modul gehört, sonst None."""
    module_id = modules.module_for_cli(args.cmd)
    if module_id is None:
        return None
    try:
        cfg = config.load_config()
    except Exception:  # noqa: BLE001 (der Befehl selbst meldet die kaputte Konfiguration)
        return None
    if modules.is_enabled(cfg, module_id):
        return None
    return str(modules.ModuleDisabled(module_id))


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    plugins = discover_commands()
    args = _parser(plugins).parse_args(argv)
    disabled = module_check(args)
    if disabled is not None:
        print(disabled, file=sys.stderr)
        return EXIT_ERROR
    try:
        with exclusive_access(args):
            if args.cmd in plugins:
                return plugins[args.cmd].run(args, make_context(args))
            return _run(args)
    except RemoteError as exc:
        print(_t("Fehler: {exc}", exc=exc), file=sys.stderr)
        return exc.exit_code
    except HANDLED_ERRORS as exc:
        print(format_error(exc), file=sys.stderr)
        return explain(exc).exit_code


if __name__ == "__main__":
    sys.exit(main())
