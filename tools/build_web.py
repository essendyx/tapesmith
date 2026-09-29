"""Baut die Web-Oberfläche (web/) nach src/tapesmith/webui/static/ und prüft das Ergebnis.

Aufruf: python tools/build_web.py [--install] [--skip-check]

--install     vorher `npm ci` (mit package-lock.json, sonst `npm install`)
--skip-check  `npm run check` (Typprüfung, ESLint, Vitest) auslassen

Danach `npm run build` und eine Prüfung, ob index.html und alle dort verlinkten
Dateien unter /assets/ vorhanden sind. Jeder Schritt läuft in web/, die Ausgabe wird durchgereicht.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT / "web"
STATIC_DIR = ROOT / "src" / "tapesmith" / "webui" / "static"
IS_WINDOWS = os.name == "nt"

_ASSET_REF = re.compile(r"""(?:src|href)\s*=\s*["']/?(assets/[^"'?#]+)""", re.IGNORECASE)


def find_npm() -> str | None:
    """Pfad zu npm oder None. Unter Windows zuerst `npm.cmd` (subprocess startet keine .ps1/Shell-Skripte)."""
    names = ("npm.cmd", "npm") if IS_WINDOWS else ("npm",)
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return None


def verify_static(static_dir: Path) -> list[str]:
    """Probleme des Builds: fehlende index.html und dort referenzierte, aber fehlende /assets/-Dateien."""
    index = static_dir / "index.html"
    if not index.is_file():
        return [f"index.html fehlt in {static_dir}"]
    html = index.read_text(encoding="utf-8")
    problems: list[str] = []
    seen: set[str] = set()
    for ref in _ASSET_REF.findall(html):
        if ref in seen:
            continue
        seen.add(ref)
        if not (static_dir / ref).is_file():
            problems.append(f"Datei fehlt: /{ref} (verlinkt in index.html)")
    return problems


Runner = Callable[..., subprocess.CompletedProcess]


def _parse(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Baut die Web-Oberfläche nach src/tapesmith/webui/static/.")
    parser.add_argument("--install", action="store_true", help="vorher npm ci (bzw. npm install) ausführen")
    parser.add_argument("--skip-check", action="store_true", help="npm run check auslassen")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None, *, runner: Runner = subprocess.run) -> int:
    args = _parse(argv)
    npm = find_npm()
    if npm is None:
        print("npm nicht gefunden: Node.js installieren", file=sys.stderr)
        return 1

    steps: list[list[str]] = []
    if args.install:
        steps.append(["ci"] if (WEB_DIR / "package-lock.json").is_file() else ["install"])
    if not args.skip_check:
        steps.append(["run", "check"])
    steps.append(["run", "build"])

    for step in steps:
        label = "npm " + " ".join(step)
        print(f"==> {label}", flush=True)
        try:
            result = runner([npm, *step], cwd=str(WEB_DIR), check=False)
        except OSError as exc:
            print(f"{label} konnte nicht gestartet werden: {exc}", file=sys.stderr)
            return 1
        if result.returncode != 0:
            print(f"{label} fehlgeschlagen (Exit {result.returncode})", file=sys.stderr)
            return 1

    problems = verify_static(STATIC_DIR)
    if problems:
        print("Build unvollständig:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    print(f"Web-Oberfläche gebaut: {STATIC_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
