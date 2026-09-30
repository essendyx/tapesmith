"""Gemeinsamer Kontext und Bausteine für CLI-Befehlsmodule (Plugins).

Jeder Druck aus der CLI läuft über `emit_labels` -> Druck-Backend (`ipc.backend`): über den
Druckdienst p12d oder (mit `--no-daemon`, ausdrücklichem `--transport`/`--hexlog` oder ohne
Dienst) direkt über `pipeline.PrintPipeline`. Preflight-Warnungen, Fehldruckschutz mit Rückfrage, Kopien/Kette, Verlauf, Export und sauberer Abbruch mit Strg+C.
Wie in der GUI zieht jeder Druck von der Rolle des aktuellen Bandes ab und warnt vorher, auch bei hohem Schwarzanteil
(gemeinsame Hooks aus `printhooks`).
"""

import argparse
import ctypes
import dataclasses
import importlib
import io
import msvcrt
import os
import pkgutil
import threading
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import TextIO

from PIL import Image

from tapesmith.archive import archive_hook
from tapesmith.config import setting
from tapesmith.device.profile import DeviceProfile
from tapesmith.export import export_heads
from tapesmith.guard import GuardRejected, load_policy
from tapesmith.history import HistoryStore
from tapesmith.ipc.backend import LocalBackend, PrintBackend, Relay, local_planner, make_backend, use_daemon
from tapesmith.jobs import CancelToken, JobMeta
from tapesmith.labelmeta import template_meta  # Re-Export: cli.py und cli_cmds/reprint.py importieren von hier
from tapesmith.pipeline import (
    PrintLabel,
    PrintOutcome,
    PrintPipeline,
    PrintRequest,
    direct_runner,
    labels_from_result,
)
from tapesmith.printer import PrinterSession
from tapesmith.printhooks import print_hooks
from tapesmith.render.chain import chain_preview
from tapesmith.render.checks import is_small_font_warning
from tapesmith.render.compose import LabelSpec, RenderResult, preview_image, render_label, rows_to_mm
from tapesmith.render.fixes import FIX_IDS, apply_fix, suggest_fixes
from tapesmith.tape.profiles import current_tape
from tapesmith.tape.rolls import RollStore
from tapesmith.i18n import _t

JOIN_INTERVAL = 0.2
YES_ANSWERS = ("j", "ja", "y", "yes")
PREVIEW_SCALE = 4


@dataclass
class CliContext:
    args: argparse.Namespace
    load_config: Callable[[], dict]
    load_profile: Callable[[], DeviceProfile]
    open_session: Callable[[DeviceProfile], AbstractContextManager[PrinterSession]]
    emit_label: Callable[[RenderResult, JobMeta], bool]
    emit_head: Callable[[Image.Image, JobMeta], bool]
    stdin: TextIO
    stdout: TextIO
    stderr: TextIO

    def out(self, text: str) -> None:
        print(text, file=self.stdout)

    def err(self, text: str) -> None:
        print(text, file=self.stderr)

    def stdin_is_tty(self) -> bool:
        return is_interactive(self.stdin)


def is_interactive(stream) -> bool:
    """Ob `stream` eine echte, bedienbare Konsole ist; Rückfragen dürfen nur dann warten.

    Unter Windows meldet `isatty()` für stdin aus `NUL` fälschlich `True` (z. B. wenn ein
    Dienst/eine Aufgabenplanung ohne Konsole startet); ohne diese Zusatzprüfung würden
    Rückfragen dort blockieren. `GetConsoleMode` schlägt für `NUL` fehl (Rückgabe 0), für eine
    echte Konsole gelingt es.
    """
    isatty = getattr(stream, "isatty", None)
    try:
        if not isatty or not isatty():
            return False
    except Exception:
        return False
    try:
        fd = stream.fileno()
    except (OSError, ValueError, io.UnsupportedOperation, AttributeError):
        return True
    if os.name == "nt":
        try:
            handle = msvcrt.get_osfhandle(fd)
            mode = ctypes.c_uint32()
            if ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(mode)) == 0:
                return False
        except Exception:
            return False
    return True


def positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(_t("muss eine ganze Zahl ≥ 1 sein")) from exc
    if value < 1:
        raise argparse.ArgumentTypeError(_t("muss eine ganze Zahl ≥ 1 sein"))
    return value


def positive_float(text: str) -> float:
    try:
        value = float(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(_t("muss eine Zahl > 0 sein")) from exc
    if not value > 0 or value == float("inf"):
        raise argparse.ArgumentTypeError(_t("muss eine Zahl > 0 sein"))
    return value


def add_print_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--preview", type=Path, help=_t("nur Vorschau als PNG schreiben, nicht drucken"))
    parser.add_argument("--copies", type=positive_int, default=1, help=_t("Anzahl Kopien"))
    parser.add_argument("--chain", action="store_true", help=_t("Kopien/Labels als Kette mit Schnittlinien"))
    parser.add_argument("--no-cut-marks", action="store_true", help=_t("keine Schnittlinien einzeichnen"))
    parser.add_argument("--cut-pause", type=positive_float, metavar=_t("SEK"),
                        help=_t("Pause zwischen Einzeljobs zum Abschneiden (Sekunden)"))
    parser.add_argument("-y", "--yes", action="store_true", help=_t("Rückfragen (Überlänge, viele Kopien) bestätigen"))
    parser.add_argument("--export", type=Path, help=_t("zusätzlich als PNG/PDF/PBM exportieren (Endung bestimmt Format)"))
    parser.add_argument("--queue", action="store_const", const=True, default=None,
                        help=_t("bei nicht erreichbarem Drucker in die Warteschlange des Druckdienstes (Default: queue.cli_default)"))


def add_fix_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--fix", choices=FIX_IDS, metavar="ID",
                        help=_t("Korrekturvorschlag anwenden ({items})", items=', '.join(FIX_IDS)))


def discover_commands() -> dict[str, ModuleType]:
    from tapesmith import cli_cmds

    commands: dict[str, ModuleType] = {}
    for _finder, name, _is_pkg in pkgutil.iter_modules(cli_cmds.__path__):
        if name.startswith("_") or name == "base":
            continue
        mod = importlib.import_module(f"tapesmith.cli_cmds.{name}")
        missing = [attr for attr in ("COMMAND", "HELP", "register", "run") if not hasattr(mod, attr)]
        if missing:
            raise RuntimeError(_t("Befehlsmodul '{name}': fehlt {items}", name=name, items=', '.join(missing)))
        if mod.COMMAND in commands:
            raise RuntimeError(_t("Befehl '{command}' doppelt definiert", command=mod.COMMAND))
        commands[mod.COMMAND] = mod
    return dict(sorted(commands.items()))


def parse_sets(items: list[str]) -> dict[str, str]:
    values = {}
    for item in items:
        key, sep, value = item.partition("=")
        if not sep or not key:
            raise ValueError(_t("--set erwartet feld=wert, nicht '{item}'", item=item))
        values[key.strip()] = value
    return values


# ---------- Korrekturvorschläge ----------

def _print_suggestions(ctx: CliContext, spec: LabelSpec, profile: DeviceProfile) -> None:
    fixes = suggest_fixes(spec, profile)
    if fixes:
        ctx.err(_t("Vorschläge:"))
        for fix in fixes:
            ctx.err(_t("  --fix {id}: {title}", id=fix.id, title=fix.title))


def render_with_fixes(ctx: CliContext, spec: LabelSpec, profile: DeviceProfile, fix_id: str | None,
                      render: Callable[[LabelSpec, DeviceProfile], RenderResult] = render_label,
                      ) -> tuple[LabelSpec, RenderResult]:
    """Rendert `spec`; mit `fix_id` wird die Korrektur vorher angewendet. Passt der Text nicht,
    nennt die Funktion die Korrekturvorschläge und reicht den Fehler weiter."""
    if fix_id:
        fix = apply_fix(spec, profile, fix_id)
        spec = fix.spec
        ctx.err(_t("Korrektur: {title}", title=fix.title))
    try:
        result = render(spec, profile)
    except ValueError:
        _print_suggestions(ctx, spec, profile)
        raise
    if not fix_id and any(is_small_font_warning(w) for w in result.warnings):
        _print_suggestions(ctx, spec, profile)
    return spec, result


# ---------- Pipeline / Backend ----------

# Tests: Fabrik (ctx, history) -> PrintBackend statt Dienst/Direktdruck.
BACKEND_FACTORY: Callable[[CliContext, HistoryStore], PrintBackend] | None = None


def _print_warning(ctx: CliContext) -> Callable[[str], None]:
    return lambda w: ctx.err(_t("Warnung: {w}", w=w))


def _print_cut_pause(ctx: CliContext) -> Callable[[str, int, int, float], None]:
    def show(state: str, done: int, total: int, sek: float) -> None:
        if state == "start":
            ctx.err(_t("Label {done}/{total} abschneiden, nächstes in {sek:.0f} s …", done=done, total=total, sek=sek))
    return show


def build_pipeline(ctx: CliContext, history: HistoryStore, *, warning_relay: Relay | None = None,
                   cut_pause_relay: Relay | None = None) -> PrintPipeline:
    """Direktdruck-Pipeline. Warnungen/Schneidpause laufen über zwei `Relay`s; ohne übergebene
    Relays gibt die Pipeline sie wie bisher über `ctx.err` aus."""
    profile = ctx.load_profile()
    cfg = ctx.load_config()
    if warning_relay is None:
        warning_relay = Relay()
        warning_relay.connect(_print_warning(ctx))
    if cut_pause_relay is None:
        cut_pause_relay = Relay()
        cut_pause_relay.connect(_print_cut_pause(ctx))
    return PrintPipeline(profile, direct_runner(lambda: ctx.open_session(profile)), history=history,
                         policy=load_policy(cfg), on_warning=warning_relay, on_cut_pause=cut_pause_relay,
                         **print_hooks(RollStore(), lambda: current_tape(cfg).id))


def _local_backend(ctx: CliContext, history: HistoryStore, reason: str = "") -> LocalBackend:
    warning_relay, cut_pause_relay = Relay(), Relay()
    pipeline = build_pipeline(ctx, history, warning_relay=warning_relay, cut_pause_relay=cut_pause_relay)
    profile = pipeline.profile
    hook = archive_hook(ctx.load_config())
    return LocalBackend(pipeline, warning_relay=warning_relay, cut_pause_relay=cut_pause_relay,
                        run_session=direct_runner(lambda: ctx.open_session(profile)),
                        post_hooks=[hook] if hook is not None else [], fallback_reason=reason)


def wants_direct(ctx: CliContext) -> bool:
    """Direktdruck erzwungen: `--no-daemon`, ausdrücklicher Transport/Hex-Log oder Dienst aus."""
    args = ctx.args
    if getattr(args, "no_daemon", False) or getattr(args, "transport", None) or getattr(args, "hexlog", None):
        return True
    return not use_daemon(ctx.load_config())


def build_backend(ctx: CliContext, history: HistoryStore) -> PrintBackend:
    """Druck-Backend für die CLI: `BACKEND_FACTORY` (Tests), Direktdruck oder Druckdienst."""
    if BACKEND_FACTORY is not None:
        backend = BACKEND_FACTORY(ctx, history)
    elif wants_direct(ctx):
        backend = _local_backend(ctx, history)
    else:
        cfg = ctx.load_config()
        profile = ctx.load_profile()
        backend = make_backend(cfg, profile, client="cli",
                               local_factory=lambda reason: _local_backend(ctx, history, reason),
                               planner=local_planner(cfg, profile))
    if backend.fallback_reason:
        ctx.err(_t("Hinweis: {fallback_reason}", fallback_reason=backend.fallback_reason))
    return backend


def _execute(ctx: CliContext, backend: PrintBackend, request: PrintRequest, *,
             enqueue_on_offline: bool = False) -> PrintOutcome:
    """Druckt in einem Hilfsthread. Strg+C bricht sauber ab: der Druck-Thread füllt den Rest
    des angekündigten Labels mit Weiß und schiebt vor; erst dann kehrt die Funktion zurück."""
    token = CancelToken()
    done = threading.Event()
    box: dict = {}

    def work() -> None:
        try:
            box["outcome"] = backend.execute(request, cancel=token, on_warning=_print_warning(ctx),
                                             on_cut_pause=_print_cut_pause(ctx),
                                             enqueue_on_offline=enqueue_on_offline)
        except BaseException as exc:  # noqa: BLE001 (wird im Hauptthread erneut geworfen)
            box["error"] = exc
        finally:
            done.set()

    # Warten über ein Event statt Thread.join: ein per Strg+C unterbrochenes join() kann in
    # Python 3.11 den Thread fälschlich als beendet melden.
    thread = threading.Thread(target=work, name="p12-druck", daemon=True)
    thread.start()
    while not done.is_set():
        try:
            done.wait(JOIN_INTERVAL)
        except KeyboardInterrupt:
            if not token.cancelled:
                ctx.err(_t("Abbruch angefordert … Rest des Labels wird weiß aufgefüllt und vorgeschoben"))
                token.cancel()
    if "error" in box:
        raise box["error"]
    return box["outcome"]


def _label_info(result: RenderResult) -> str:
    return (_t("{length_mm:.1f} mm Inhalt, ca. {tape_mm:.0f} mm Band", length_mm=result.length_mm, tape_mm=result.tape_mm)
            + (_t(", Schrift {font_size}", font_size=result.font_size) if result.font_size else ""))


def _ask_confirmation(ctx: CliContext, reasons: tuple[str, ...]) -> None:
    text = "; ".join(reasons)
    if not ctx.stdin_is_tty():
        raise ValueError(_t("Rückfrage nötig ({text}), mit --yes bestätigen", text=text))
    ctx.err(_t("Rückfrage: {text}", text=text))
    print(_t("Wirklich drucken? [j/N] "), end="", file=ctx.stderr, flush=True)
    answer = ctx.stdin.readline().strip().lower()
    if answer not in YES_ANSWERS:
        ctx.err(_t("Nicht gedruckt"))
        raise ValueError(_t("Druck nicht bestätigt"))


def _write_preview(path: Path, profile: DeviceProfile, plan, labels: tuple[PrintLabel, ...],
                   result: RenderResult | None, multi: bool) -> None:
    if multi:
        chain_preview(plan.chain, profile, scale=PREVIEW_SCALE).save(path)
    elif result is not None:
        preview_image(result).save(path)
    else:
        land = labels[0].head.rotate(90, expand=True)
        land.resize((land.width * PREVIEW_SCALE, land.height * PREVIEW_SCALE), Image.NEAREST).save(path)


def _info_text(profile: DeviceProfile, labels: tuple[PrintLabel, ...], result: RenderResult | None) -> str:
    return (_label_info(result) if result is not None
            else f"{rows_to_mm(labels[0].head.height, profile):.1f} mm")


def emit_labels(ctx: CliContext, labels: tuple[PrintLabel, ...], meta: JobMeta,
                result: RenderResult | None = None, *,
                copies: int | None = None, chain: bool | None = None,
                confirmed: bool | None = None) -> bool:
    """Führt Labels durch das Druck-Backend. Rückgabe True = gedruckt (oder in die Warteschlange
    des Druckdienstes gestellt), False = nur Vorschau.

    `copies`/`chain`/`confirmed` None -> aus den Kommandozeilenoptionen (Default 1/False/False).
    """
    args = ctx.args
    if result is not None:
        for warning in result.warnings:
            ctx.err(_t("Warnung: {warning}", warning=warning))
    copies = copies if copies is not None else (getattr(args, "copies", None) or 1)
    chain = chain if chain is not None else bool(getattr(args, "chain", False))
    confirmed = confirmed if confirmed is not None else bool(getattr(args, "yes", False))
    request = PrintRequest(labels, meta, copies=copies, chain=chain,
                           cut_marks=not getattr(args, "no_cut_marks", False), confirmed=confirmed,
                           cut_pause_s=getattr(args, "cut_pause", None))
    multi = copies > 1 or chain or len(labels) > 1
    export_path = getattr(args, "export", None)
    preview_path = getattr(args, "preview", None)

    if preview_path:
        # Vorschau druckt nie: lokal planen, ohne Druckdienst zu starten.
        profile = ctx.load_profile()
        plan = local_planner(ctx.load_config(), profile)(request)
        info = _info_text(profile, labels, result)
        if export_path:
            export_heads(export_path, [job.head for job in plan.chain.jobs], profile)
            ctx.out(_t("Export: {export_path}", export_path=export_path))
        _write_preview(preview_path, profile, plan, labels, result, multi)
        suffix = f" · {plan.balance_text}" if multi else ""
        ctx.out(_t("Vorschau: {preview_path} ({info}{suffix})", preview_path=preview_path, info=info, suffix=suffix))
        return False

    with HistoryStore() as history:
        backend = build_backend(ctx, history)
        try:
            return _print(ctx, backend, request, labels, result, multi, export_path)
        finally:
            backend.close()


def _print(ctx: CliContext, backend: PrintBackend, request: PrintRequest, labels: tuple[PrintLabel, ...],
           result: RenderResult | None, multi: bool, export_path: Path | None) -> bool:
    profile = ctx.load_profile()
    plan = backend.plan(request)
    info = _info_text(profile, labels, result)
    if export_path:
        export_heads(export_path, [job.head for job in plan.chain.jobs], profile)
        ctx.out(_t("Export: {export_path}", export_path=export_path))

    enqueue = getattr(ctx.args, "queue", None)
    if enqueue is None:
        enqueue = setting(ctx.load_config(), "queue.cli_default")
    enqueue = bool(enqueue)

    outcome = _execute(ctx, backend, request, enqueue_on_offline=enqueue)
    if outcome.status == "bestätigung_nötig":
        _ask_confirmation(ctx, outcome.reasons)
        request = dataclasses.replace(request, confirmed=True)
        outcome = _execute(ctx, backend, request, enqueue_on_offline=enqueue)

    if outcome.status == "wartet":
        ctx.out(_t("Drucker nicht erreichbar, Auftrag wartet in der Warteschlange (#{queue_id}) (tapesmith queue list)", queue_id=outcome.queue_id))
        return True
    if outcome.status == "abgelehnt":
        if not outcome.plan.decision.allowed:
            raise GuardRejected(outcome.plan.decision)
        raise ValueError("; ".join(outcome.reasons))
    if outcome.status == "unvollständig":
        if outcome.error is not None:
            raise outcome.error
        raise ValueError(_t("Druck unvollständig"))
    if outcome.status == "abgebrochen":
        ctx.err(_t("Druck abgebrochen, Drucker hat sauber mit Vorschub abgeschlossen"))
        raise ValueError(_t("Druck abgebrochen"))
    if outcome.status != "ok":
        raise ValueError(_t("Druck nicht ausgeführt: {items}", items='; '.join(outcome.reasons)))

    history_note = _t(" (Verlauf #{history_id})", history_id=outcome.history_id) if outcome.history_id is not None else ""
    if result is not None:
        ctx.out(f"gedruckt: {info}{history_note}")
    else:
        rows = sum(r.rows for r in outcome.results)
        waited = sum(r.waited_s for r in outcome.results)
        ctx.out(_t("gedruckt: {rows} Zeilen ({value:.1f} mm), gewartet {waited:.1f} s{history_note}", rows=rows, value=rows / profile.dots_per_mm, waited=waited, history_note=history_note))
    if multi:
        ctx.out(_t("Band: {balance_text}", balance_text=plan.balance_text))
    return True


def default_emit_label(ctx: CliContext, result: RenderResult, meta: JobMeta) -> bool:
    return emit_labels(ctx, labels_from_result(result), meta, result)


def default_emit_head(ctx: CliContext, head: Image.Image, meta: JobMeta) -> bool:
    return emit_labels(ctx, (PrintLabel(head),), meta)
