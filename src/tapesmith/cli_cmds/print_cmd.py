"""'tapesmith print': Text (Argumente oder stdin) oder ein vorhandenes Bild (--image) drucken."""

from pathlib import Path

from tapesmith.cli_cmds import base as cmd_base
from tapesmith.cli_cmds.base import add_fix_option, add_print_options
from tapesmith.document.render import render_spec
from tapesmith.imageinput import ROTATE_MODES, load_image_head, read_stdin_text
from tapesmith.jobs import JobMeta, spec_to_dict
from tapesmith.render.compose import LabelSpec
from tapesmith.tape.profiles import current_tape
from tapesmith.i18n import N_, _t

COMMAND = "print"
HELP = N_("Text (auch von stdin) oder Bilddatei drucken")


def register(parser) -> None:
    parser.add_argument("lines", nargs="*", help=_t("eine Zeile pro Argument; '-' liest stdin"))
    parser.add_argument("--image", type=Path, help=_t("Bilddatei (PNG/PBM) statt Text drucken"))
    parser.add_argument("--fit", action="store_true", help=_t("zu große Bilder verkleinern"))
    parser.add_argument("--rotate", default="auto", choices=ROTATE_MODES)
    parser.add_argument("--threshold", type=int, default=128)
    parser.add_argument("--font", default="sans", choices=["sans", "sans-bold", "mono"])
    parser.add_argument("--align", default="left", choices=["left", "center", "right"])
    parser.add_argument("--size", type=int, help=_t("feste Schriftgröße statt Auto-Fit"))
    length_group = parser.add_mutually_exclusive_group()
    length_group.add_argument("--max-mm", type=float, help=_t("maximale Labellänge in mm"))
    length_group.add_argument("--length-mm", type=float, help=_t("feste Labellänge in mm"))
    parser.add_argument("--qr", help=_t("QR-Inhalt links neben dem Text"))
    add_fix_option(parser)
    add_print_options(parser)


def run(args, ctx) -> int:
    profile = ctx.load_profile()

    if args.image:
        if args.lines:
            raise ValueError(_t("Text und --image nicht zugleich angeben"))
        head = load_image_head(args.image, profile, threshold=args.threshold,
                                rotate=args.rotate, fit=args.fit)
        ctx.emit_head(head, JobMeta(kind="image", title=args.image.name))
        return 0

    lines = args.lines
    if lines == ["-"] or (not lines and not ctx.stdin_is_tty()):
        lines = read_stdin_text(ctx.stdin)
    if not lines:
        raise ValueError(_t("Kein Text angegeben: Text als Argument, über stdin oder --image"))
    if len(lines) > 3:
        raise ValueError(_t("höchstens 3 Zeilen erlaubt, {count} angegeben", count=len(lines)))

    spec = LabelSpec(lines=tuple(lines), font=args.font, align=args.align, font_size=args.size,
                      max_length_mm=args.max_mm, fixed_length_mm=args.length_mm, qr=args.qr)
    tape = current_tape(ctx.load_config())
    spec, result = cmd_base.render_with_fixes(ctx, spec, profile, args.fix,
                                              render=lambda s, p: render_spec(s, p, tape))
    ctx.emit_label(result, JobMeta(kind="text", title=" ".join(spec.lines), spec=spec_to_dict(spec)))
    return 0
