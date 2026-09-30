"""Dünne Kompatibilitätsbefehle für die Alt-Werkzeuge von soburi (phomemo-p12-tools 0.0.5),
damit bestehende Skripte weiterlaufen. Verhalten nachgebildet, Quelltext nicht kopiert."""

import argparse
import binascii
import dataclasses
import sys
import time
from pathlib import Path

from PIL import Image

from tapesmith import paths
from tapesmith.config import load_config
from tapesmith.device.profile import load_profile
from tapesmith.imageinput import load_image_head
from tapesmith.lock import PrinterBusy
from tapesmith.printer import PrinterSession
from tapesmith.protocol.job import build_job, job_bytes
from tapesmith.protocol.raster import landscape_to_content
from tapesmith.render.compose import LabelSpec, render_label
from tapesmith.transport.base import TransportError
from tapesmith.transport.resolve import open_transport
from tapesmith.i18n import N_, _t

HINT_PRINT = N_("Hinweis: phomemo_print_p12 ist ein Kompatibilitätsbefehl, künftig: tapesmith print --image DATEI")
HINT_RENDER = N_('Hinweis: phomemo_render_label ist ein Kompatibilitätsbefehl, künftig: tapesmith text "…" --preview datei.png')
SLEEP = time.sleep


def _utf8_streams() -> None:
    """Windows-Konsolen liefern sonst cp1252, wie in `cli.main`."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")


def pbm_ascii(img: Image.Image) -> str:
    """ASCII-PBM (P1): 1 = schwarz, 0 = weiß (Gegenteil unserer internen Konvention)."""
    mono = img.convert("1")
    w, h = mono.size
    px = mono.load()
    rows = [" ".join("1" if px[x, y] == 0 else "0" for x in range(w)) for y in range(h)]
    return "P1\n" + f"{w} {h}\n" + "\n".join(rows) + "\n"


def _font_for(name: str) -> tuple[str, str | None]:
    if name == "":
        return "sans", None
    lowered = name.lower()
    if "mono" in lowered:
        return "mono", None
    if "bold" in lowered:
        return "sans-bold", None
    return "sans", _t("Schrift '{name}' nicht verfügbar, nutze DejaVu Sans", name=name)


def render_label_main(argv: list[str] | None = None, stdout=None, stderr=None) -> int:
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    parser = argparse.ArgumentParser(prog="phomemo_render_label")
    parser.add_argument("--font", default="")
    parser.add_argument("--font-size", type=int, default=0)
    parser.add_argument("--width", type=int, default=96)
    parser.add_argument("--margin", type=int, default=8)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("text")
    args = parser.parse_args(argv)

    print(_t(HINT_RENDER), file=stderr)
    if args.offset != 0:
        print(_t("Hinweis: --offset wird ignoriert"), file=stderr)

    font, font_warning = _font_for(args.font)
    if font_warning:
        print(font_warning, file=stderr)

    try:
        profile = load_profile(calibration_path=paths.calibration_path())
        height = args.width - args.margin
        if height > profile.content_dots:
            raise ValueError(
                _t("Höhe {height} Punkte (--width {width} - --margin {margin}) überschreitet das Profil ({content_dots} Punkte)", height=height, width=args.width, margin=args.margin, content_dots=profile.content_dots))
        prof = dataclasses.replace(profile, content_dots=height)
        font_size = None if args.font_size == 0 else args.font_size
        spec = LabelSpec(lines=(args.text,), font=font, font_size=font_size)
        result = render_label(spec, prof)
    except ValueError as exc:
        print(_t("Fehler: {exc}", exc=exc), file=stderr)
        return 1

    stdout.write(pbm_ascii(landscape_to_content(result.landscape)))
    return 0


def main_render() -> None:
    _utf8_streams()
    sys.exit(render_label_main())


def print_p12_main(argv: list[str] | None = None, stdin=None, stderr=None) -> int:
    stdin = sys.stdin if stdin is None else stdin
    stderr = sys.stderr if stderr is None else stderr
    parser = argparse.ArgumentParser(prog="phomemo_print_p12")
    parser.add_argument("--port", required=True)
    parser.add_argument("--dots", type=int, default=96)
    parser.add_argument("filename", nargs="?")
    args = parser.parse_args(argv)

    print(_t(HINT_PRINT), file=stderr)

    try:
        profile = load_profile(calibration_path=paths.calibration_path())
        if args.dots != profile.head_dots:
            raise ValueError(_t("nur {head_dots} Punkte unterstützt", head_dots=profile.head_dots))

        if args.filename:
            source = Path(args.filename)
        else:
            buffer = getattr(stdin, "buffer", stdin)
            source = buffer.read()
        head = load_image_head(source, profile, rotate="none")

        if args.port == "dummy":
            data = job_bytes(build_job(head, profile))
            block_size = args.dots // 8
            for i in range(0, len(data), block_size):
                print(binascii.hexlify(data[i:i + block_size]), file=stderr)
            return 0

        cfg = load_config()
        transport = open_transport(args.port, cfg["mac"], open_timeout=float(cfg["connect_timeout_s"]))
        with PrinterSession(transport, profile, sleep=SLEEP) as session:
            session.print_image(head)
        return 0
    except PrinterBusy as exc:
        print(_t("Fehler: {exc}", exc=exc), file=stderr)
        return 7
    except TransportError as exc:
        print(_t("Fehler: {exc}", exc=exc), file=stderr)
        return 5
    except (ValueError, OSError) as exc:
        print(_t("Fehler: {exc}", exc=exc), file=stderr)
        return 1


def main_print() -> None:
    _utf8_streams()
    sys.exit(print_p12_main())
