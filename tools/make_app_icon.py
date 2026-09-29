"""Erzeugt `src/tapesmith/icons/app.ico`: App-Symbol für EXE und Verknüpfungen, aus
`tapesmith.gui.icons.draw_icon_image` in allen `ICON_SIZES`, ohne Statuspunkt (kein Status
außerhalb der Tray-App). Jede Größe wird einzeln gezeichnet (nicht aus der größten Größe
herunterskaliert), damit z. B. unter 32 px die feineren Linien wegfallen wie im Tray-Symbol.

Aufruf: .venv\\Scripts\\python tools\\make_app_icon.py [--out DATEI]
`--check` vergleicht nur mit der eingecheckten Datei (Exit 1 bei Abweichung, schreibt nichts).
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from tapesmith.gui.icons import ICON_SIZES, draw_icon_image  # noqa: E402

TARGET = REPO_ROOT / "src" / "tapesmith" / "icons" / "app.ico"


def build_ico_bytes() -> bytes:
    """ICO-Bytes mit allen `ICON_SIZES`, jede Größe einzeln gezeichnet (kein Statuspunkt)."""
    images = [draw_icon_image(size, None, dark_taskbar=False) for size in sorted(ICON_SIZES, reverse=True)]
    buf = io.BytesIO()
    images[0].save(buf, format="ICO", sizes=[(img.width, img.height) for img in images],
                   append_images=images[1:])
    return buf.getvalue()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=TARGET, help="Zielpfad (Standard: eingecheckte Datei)")
    parser.add_argument("--check", action="store_true",
                        help="nur gegen die eingecheckte Datei vergleichen, nichts schreiben")
    args = parser.parse_args(argv)

    data = build_ico_bytes()
    if args.check:
        if not args.out.exists():
            print(f"{args.out} fehlt, bitte tools/make_app_icon.py ausführen")
            return 1
        if args.out.read_bytes() != data:
            print(f"{args.out} weicht vom erzeugten Symbol ab, bitte tools/make_app_icon.py neu ausführen")
            return 1
        print(f"{args.out} ist aktuell")
        return 0

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(data)
    print(f"{args.out} geschrieben ({len(ICON_SIZES)} Größen)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
