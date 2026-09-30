"""Plugin-Befehl 'tapesmith density': Dichte-Teststreifen (experimentell).

Druckt je Dichte-Kandidat einen Teststreifen (Kandidatenbefehl als `prelude`, wird nie ohne diese
Aktion gesendet). Der gewählte Wert wird nur im Bandprofil gespeichert, nicht automatisch
gesendet, bis ein HCI-Snoop-Mitschnitt oder Teststreifen einen Befehl belegt.
"""

import argparse
from pathlib import Path

from PIL import Image

from tapesmith.density import (
    DEFAULT_VALUES,
    FAMILIES,
    PRINT_MASTER_NOTE,
    WARNING,
    density_candidates,
    density_test_head,
)
from tapesmith.tape.profiles import current_tape, save_tape_density
from tapesmith.i18n import N_, _t

COMMAND = "density"
HELP = N_("Dichte-Teststreifen (experimentell)")

YES_ANSWERS = ("j", "ja", "y", "yes")


def register(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--family", choices=sorted(FAMILIES), default="m110", help=_t("Dichte-Kandidatenfamilie"))
    parser.add_argument("--values", default=",".join(str(v) for v in DEFAULT_VALUES),
                        help=_t("kommagetrennte Werte 1..15 (Default 3,8,12)"))
    parser.add_argument("--length-mm", type=float, default=45.0, help=_t("Länge je Teststreifen in mm"))
    parser.add_argument("--yes", action="store_true", help=_t("Rückfrage vor dem Druck bestätigen"))
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--save", type=int, metavar="N", help=_t("Feld N direkt im Bandprofil speichern"))
    group.add_argument("--no-save", action="store_true", help=_t("nicht nach dem besten Feld fragen"))
    parser.add_argument("--preview", type=Path, metavar=_t("DATEI.png"),
                        help=_t("nur die Teststreifen untereinander als PNG schreiben, nicht drucken"))


def _parse_values(text: str) -> list[int]:
    try:
        return [int(v.strip()) for v in text.split(",") if v.strip()]
    except ValueError as exc:
        raise ValueError(_t("--values erwartet kommagetrennte Zahlen, nicht '{text}'", text=text)) from exc


def _stack(images: list[Image.Image]) -> Image.Image:
    width = max(img.width for img in images)
    height = sum(img.height for img in images)
    canvas = Image.new("1", (width, height), 255)
    y = 0
    for img in images:
        canvas.paste(img, (0, y))
        y += img.height
    return canvas


def _ask_field(ctx, candidates) -> tuple[int, str] | None:
    print(_t("Welches Feld war am besten? (Nummer, leer = keins) "), end="", file=ctx.stderr, flush=True)
    answer = ctx.stdin.readline().strip()
    if not answer:
        return None
    try:
        number = int(answer)
    except ValueError as exc:
        raise ValueError(_t("Ungültige Feldnummer '{answer}'", answer=answer)) from exc
    chosen = next((c for c in candidates if c.number == number), None)
    if chosen is None:
        raise ValueError(_t("Feld {number} gibt es nicht (1..{count})", number=number, count=len(candidates)))
    return chosen.value, chosen.family


def run(args: argparse.Namespace, ctx) -> int:
    profile = ctx.load_profile()
    cfg = ctx.load_config()
    values = _parse_values(args.values)
    candidates = density_candidates(args.family, values)
    heads = [density_test_head(c, profile, args.length_mm) for c in candidates]

    ctx.err(_t(WARNING))
    ctx.err(_t(PRINT_MASTER_NOTE))

    if args.preview:
        _stack(heads).save(args.preview)
        ctx.out(_t("Vorschau: {preview}", preview=args.preview))
        return 0

    if not args.yes:
        if not ctx.stdin_is_tty():
            raise ValueError(_t("Rückfrage nötig (Dichte-Teststreifen drucken), mit --yes bestätigen"))
        ctx.err(_t("Rückfrage: Dichte-Teststreifen wirklich drucken?"))
        print(_t("Wirklich drucken? [j/N] "), end="", file=ctx.stderr, flush=True)
        answer = ctx.stdin.readline().strip().lower()
        if answer not in YES_ANSWERS:
            ctx.err(_t("Nicht gedruckt"))
            raise ValueError(_t("Druck nicht bestätigt"))

    with ctx.open_session(profile) as s:
        for c, head in zip(candidates, heads):
            s.print_image(head, prelude=c.command)
            ctx.out(_t("gedruckt: {label} (nicht im Restmeter erfasst)", label=c.label))

    if args.no_save:
        return 0

    if args.save is not None:
        chosen = next((c for c in candidates if c.number == args.save), None)
        if chosen is None:
            raise ValueError(_t("Feld {save} gibt es nicht (1..{count})", save=args.save, count=len(candidates)))
        choice = (chosen.value, chosen.family)
    elif ctx.stdin_is_tty():
        choice = _ask_field(ctx, candidates)
    else:
        choice = None

    if choice is None:
        return 0

    value, family = choice
    tape = current_tape(cfg)
    save_tape_density(tape.id, value, family)
    ctx.out(_t("Gespeichert im Bandprofil {name} (experimentell, wird nicht automatisch gesendet)", name=tape.name))
    return 0
