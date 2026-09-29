"""Baut die portable Onedir-Variante von Tapesmith.

Eine EXE für alle Prozessarten: ohne Argument bzw. mit `--app` öffnet sie die Web-Oberfläche im
Standardbrowser, dazu `--daemon`, `--tray`, `--selftest`. Die gebaute Web-Oberfläche
(`webui/static`) kommt über `data_files()` automatisch mit, uvicorn über Hidden-Imports. Ein eigenes
Fenster (pywebview, WebView2, pythonnet) gibt es nicht mehr; diese Pakete werden ausdrücklich
ausgeschlossen, falls sie im venv noch installiert sind.

Standard-Backend PyInstaller (--onedir --windowed, kein Onefile: Kaltstart 3-8 s und
Defender-Fehlalarme wuerden den 5-s-Schnelldruck unterlaufen). Nuitka-Kommando wird
nur erzeugt/angezeigt und nicht ausgefuehrt, ausser --backend nuitka wird
ausdruecklich gewaehlt. Nach dem Build laeuft der eingebaute Selbsttest
(Tapesmith.exe --selftest --selftest-out datei) offscreen, ohne zu drucken.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import re
import subprocess
import sys
import time
import zipfile
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG_DIR = ROOT / "src" / "tapesmith"
ENTRY = ROOT / "tools" / "tapesmith_gui_entry.py"
APP_NAME = "Tapesmith"
# `ppf` ist ein Namespace-Paket, `openpyxl` wird nur innerhalb einer Funktion importiert.
# Druckdienst und Tray laufen aus derselben EXE (`--daemon`/`--tray`, spät importiert).
# Browserstart (`--app`, Standard ohne Argument), Web-API im Dienst, Qt-freier Selbsttest;
# uvicorn wählt Schleife, HTTP-Protokoll und Lifespan zur Laufzeit per Name.
HIDDEN_IMPORTS = ("ppf.datamatrix", "openpyxl", "tapesmith.daemon.instance", "tapesmith.gui.tray",
                  "tapesmith.webui.browser", "tapesmith.webapi.app", "tapesmith.webapi.server",
                  "tapesmith.selftest", "uvicorn.loops.auto", "uvicorn.loops.asyncio",
                  "uvicorn.protocols.http.auto", "uvicorn.protocols.http.h11_impl", "uvicorn.lifespan.off")
# Nur mitnehmen, wenn installiert. BLE: `bleak` lädt seine Backends dynamisch.
OPTIONAL_COLLECT = ("bleak", "cryptography")
# Nie mitnehmen: das frühere App-Fenster (pywebview mit WebView2 über pythonnet). Die Oberfläche
# läuft nur noch im Standardbrowser; ein im venv verbliebenes pywebview soll nicht im Build landen.
EXCLUDED_MODULES = ("tkinter", "webview", "clr", "clr_loader", "pythonnet")
# zxing-cpp (Barcode-Decoder) lädt tapesmith.render.zxing per importlib, optional: Smart App Control
# kann die .pyd blockieren, das Programm läuft dann ohne Rücklesen weiter.
OPTIONAL_HIDDEN_IMPORTS = ("winrt.windows.devices.bluetooth", "zxingcpp")
BUILD_TIMEOUT_S = 900  # 15 min
SMOKE_TIMEOUT_S = 120


def data_files(pkg_dir: Path = PKG_DIR) -> list[tuple[Path, str]]:
    """Alle Paketdaten (keine .py/.pyc, kein __pycache__) mit Zielordner im Bundle."""
    prefix = pkg_dir.name
    result: list[tuple[Path, str]] = []
    for path in pkg_dir.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix in (".py", ".pyc"):
            continue
        if "__pycache__" in path.parts:
            continue
        rel_parent = path.relative_to(pkg_dir).parent
        target = prefix if rel_parent == Path(".") else f"{prefix}/{rel_parent.as_posix()}"
        result.append((path, target))
    result.sort(key=lambda item: item[0])
    return result


def module_available(name: str) -> bool:
    """True, wenn `name` importierbar ist (ohne es zu importieren; fehlende Elternpakete -> False)."""
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def pyinstaller_args(*, dist: Path, work: Path, entry: Path = ENTRY, name: str = APP_NAME,
                     available: Callable[[str], bool] = module_available,
                     pkg_dir: Path = PKG_DIR) -> list[str]:
    args = [
        "--noconfirm", "--clean", "--onedir", "--windowed",
        "--name", name,
        "--distpath", str(dist),
        "--workpath", str(work),
        "--specpath", str(work),
        "--paths", str(ROOT / "src"),
        "--collect-submodules", "tapesmith",
    ]
    for module in EXCLUDED_MODULES:
        args += ["--exclude-module", module]
    for package in OPTIONAL_COLLECT:
        if available(package):
            args += ["--collect-submodules", package]
    for module in HIDDEN_IMPORTS:
        args += ["--hidden-import", module]
    for module in OPTIONAL_HIDDEN_IMPORTS:
        if available(module):
            args += ["--hidden-import", module]
    for source, target in data_files():
        args += ["--add-data", f"{source}{os.pathsep}{target}"]
    icon = pkg_dir / "icons" / "app.ico"
    if icon.exists():
        args += ["--icon", str(icon)]
    args.append(str(entry))
    return args


def nuitka_args(*, dist: Path, entry: Path = ENTRY, name: str = APP_NAME) -> list[str]:
    return [
        "-m", "nuitka",
        "--standalone",
        "--assume-yes-for-downloads",
        "--enable-plugin=pyside6",
        "--windows-console-mode=disable",
        "--include-package=tapesmith",
        "--include-package-data=tapesmith",
        f"--output-dir={dist}",
        f"--output-filename={name}.exe",
        str(entry),
    ]


def build_env(environ: dict[str, str] | None = None) -> dict[str, str]:
    """Umgebung für den Build: `src/` dieses Checkouts vorn im PYTHONPATH. PyInstaller importiert
    `tapesmith` für `--collect-submodules` in einem Hilfsprozess; ohne diesen Eintrag fände er eine
    editierbare Installation eines anderen Checkouts (z. B. beim Build aus einem Worktree) und
    sammelte dessen Modulliste."""
    env = dict(os.environ if environ is None else environ)
    parts = [str(ROOT / "src")] + [p for p in env.get("PYTHONPATH", "").split(os.pathsep) if p]
    env["PYTHONPATH"] = os.pathsep.join(parts)
    return env


def build(*, backend: str = "pyinstaller", dist: Path = ROOT / "dist", work: Path = ROOT / "build" / "pyinstaller",
          run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
          timeout_s: float = BUILD_TIMEOUT_S) -> Path:
    if backend == "pyinstaller":
        args = [sys.executable, "-m", "PyInstaller", *pyinstaller_args(dist=dist, work=work)]
        exe = dist / APP_NAME / f"{APP_NAME}.exe"
    elif backend == "nuitka":
        args = [sys.executable, *nuitka_args(dist=dist)]
        exe = dist / f"{ENTRY.stem}.dist" / f"{APP_NAME}.exe"
    else:
        raise ValueError(f"Unbekanntes Backend: {backend}")

    try:
        run(args, cwd=ROOT, check=True, timeout=timeout_s, env=build_env())
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Build dauerte länger als 15 min, abgebrochen") from exc

    if not exe.exists():
        raise RuntimeError(f"Build fertig, aber EXE fehlt: {exe}")
    return exe


def smoke_test(exe: Path, out: Path, *, run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
                timeout_s: float = SMOKE_TIMEOUT_S) -> bool:
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "TAPESMITH_HOME": str(out.parent / "selftest-home")}
    try:
        result = run([str(exe), "--selftest", "--selftest-out", str(out)], env=env, timeout=timeout_s)
    except (subprocess.TimeoutExpired, OSError):
        # OSError z. B. WinError 4551 "Anwendungssteuerungsrichtlinie hat diese Datei blockiert"
        # (Defender/AppLocker/WDAC gegen die frisch gebaute, unsignierte EXE), kein Programmfehler.
        return False
    if result.returncode != 0:
        return False
    if not out.exists():
        return False
    lines = [line for line in out.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines:
        return False
    return lines[-1] == "Selbsttest ok"


def smoke_test_with_retry(exe: Path, out: Path, *, attempts: int = 2, pause_s: float = 5.0,
                          test=None, sleep=time.sleep) -> bool:
    """Selbsttest mit einem zweiten Versuch: der allererste Start einer frisch gebauten,
    unsignierten EXE scheitert unter Smart App Control gelegentlich, der nächste läuft."""
    test = test or smoke_test
    for attempt in range(1, attempts + 1):
        if test(exe, out):
            return True
        if attempt < attempts:
            print(f"Selbsttest Versuch {attempt} fehlgeschlagen, neuer Versuch in {pause_s:.0f} s", file=sys.stderr)
            sleep(pause_s)
    return False


INSTALLIEREN_CMD = "@echo off\r\n\"%~dp0Tapesmith\\Tapesmith.exe\" --install\r\n"


def make_zip(app_dir: Path, zip_path: Path) -> Path:
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(p for p in app_dir.rglob("*") if p.is_file()):
            zf.write(path, path.relative_to(app_dir.parent))
        zf.writestr("Installieren.cmd", INSTALLIEREN_CMD)
    return zip_path


def _read_version() -> str:
    text = (ROOT / "src" / "tapesmith" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    if not match:
        raise RuntimeError("Version nicht gefunden in src/tapesmith/__init__.py")
    return match.group(1)


def _dry_run_command(backend: str, dist: Path, work: Path) -> list[str]:
    if backend == "pyinstaller":
        return [sys.executable, "-m", "PyInstaller", *pyinstaller_args(dist=dist, work=work)]
    if backend == "nuitka":
        return [sys.executable, *nuitka_args(dist=dist)]
    raise ValueError(f"Unbekanntes Backend: {backend}")


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="build_portable", description="Baut die portable Tapesmith-App (PyInstaller onedir)")
    p.add_argument("--backend", choices=("pyinstaller", "nuitka"), default="pyinstaller")
    p.add_argument("--dist", type=Path, default=ROOT / "dist")
    p.add_argument("--zip", action="store_true", help="Nach dem Build ein Zip erzeugen")
    p.add_argument("--dry-run", action="store_true", help="Nur das Kommando ausgeben, nicht bauen")
    p.add_argument("--skip-smoke", action="store_true", help="Selbsttest nach dem Build auslassen")
    return p


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    args = _parser().parse_args(argv)
    work = ROOT / "build" / "pyinstaller"

    if args.dry_run:
        try:
            cmd = _dry_run_command(args.backend, args.dist, work)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(" ".join(str(part) for part in cmd))
        return 0

    start = time.monotonic()
    try:
        exe = build(backend=args.backend, dist=args.dist, work=work)
    except (RuntimeError, ValueError) as exc:
        print(f"Build fehlgeschlagen: {exc}", file=sys.stderr)
        return 1
    duration = time.monotonic() - start
    print(f"Build fertig in {duration:.1f} s: {exe}")

    if not args.skip_smoke:
        selftest_out = args.dist / "selftest.txt"
        ok = smoke_test_with_retry(exe, selftest_out)
        if selftest_out.exists():
            print(selftest_out.read_text(encoding="utf-8"))
        if not ok:
            print("Selbsttest fehlgeschlagen", file=sys.stderr)
            return 1

    if args.zip:
        version = _read_version()
        zip_path = make_zip(exe.parent, args.dist / f"{APP_NAME}-portable-{version}.zip")
        print(f"Zip erstellt: {zip_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
