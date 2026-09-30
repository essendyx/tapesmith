"""Versionsumgebungen: je Tapesmith-Version eine eigene Python-Umgebung (venv) unter
`<Wurzel>\\versions\\<v>`.

Ablauf von `provision`: `python -m venv versions\\<v>` mit dem Basis-Python, darin
`python -m pip install --only-binary=:all: …` (beim Update mit `--require-hashes -r lock.txt`, also
nur Pakete, deren SHA-256 in der signierten Lock-Liste steht), Kontrolle der installierten
Tapesmith-Version, Selbsttest `pythonw -m tapesmith.selftest` in der neuen Umgebung mit eigenem
Temp-Datenordner und zuletzt die Abschlussmarke `tapesmith-version.json`. Scheitert ein Schritt,
wird der halbfertige Ordner entfernt.

Es entsteht keine eigene EXE: gestartet wird immer das signierte `python.exe`/`pythonw.exe`
der Umgebung mit `-m`. Alle Unterprozesse laufen ohne Konsolenfenster (`CREATE_NO_WINDOW`), damit
ein Update aus dem Druckdienst heraus kein Fenster aufblitzen lässt. Tests ersetzen `run`."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from tapesmith.install import layout
from tapesmith.i18n import _t

CREATE_NO_WINDOW = 0x08000000
VENV_TIMEOUT_S = 300.0
PIP_TIMEOUT_S = 1800.0
SELFTEST_TIMEOUT_S = 300.0
SELFTEST_OK = "Selbsttest ok"
SELFTEST_MODULE = "tapesmith.selftest"
_OUTPUT_TAIL = 1500

# Umgebungsvariablen, die eine fremde Python-Umgebung in die neue hineinziehen würden.
_ISOLATE_ENV = ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONEXECUTABLE", "__PYVENV_LAUNCHER__",
                "VIRTUAL_ENV")

Runner = Callable[..., "subprocess.CompletedProcess"]


class ProvisionError(RuntimeError):
    """Schritt `step` (`venv`, `pip`, `version`, `selftest`) ist gescheitert; `output` ist das
    Ende der Ausgabe des Unterprozesses."""

    def __init__(self, step: str, message: str, output: str = ""):
        super().__init__(message)
        self.step = step
        self.output = output


def clean_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k.upper() not in _ISOLATE_ENV}
    env["PYTHONNOUSERSITE"] = "1"
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    env.update(extra or {})
    return env


def run_hidden(argv: Sequence[str], *, env: dict[str, str] | None = None,
               timeout: float | None = None) -> subprocess.CompletedProcess:
    """`subprocess.run` ohne Konsolenfenster, Ausgabe als Text (UTF-8, Fehler ersetzt)."""
    return subprocess.run(list(argv), env=env if env is not None else clean_env(), timeout=timeout,
                          stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0)


# ---------- Basis-Python ----------

def base_python(executable: str | None = None) -> Path:
    """`python.exe` der Basisinstallation, aus der neue Umgebungen entstehen. In einer venv ist
    das `sys._base_executable`, sonst `sys.executable`; `pythonw.exe` wird zu `python.exe`."""
    exe = Path(executable or getattr(sys, "_base_executable", None) or sys.executable)
    if exe.name.lower() == "pythonw.exe":
        exe = exe.with_name("python.exe")
    return exe


def read_pyvenv_cfg(env_dir: Path) -> dict[str, str]:
    """Schlüssel-Wert-Paare aus `<env>\\pyvenv.cfg` (leer, wenn nicht lesbar)."""
    result: dict[str, str] = {}
    try:
        text = (Path(env_dir) / layout.VENV_MARKER).read_text(encoding="utf-8")
    except OSError:
        return result
    for line in text.splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            result[key.strip().lower()] = value.strip()
    return result


def python_of_env(env_dir: Path) -> Path | None:
    """Basis-`python.exe`, mit dem die Umgebung `env_dir` angelegt wurde (`home` in pyvenv.cfg)."""
    home = read_pyvenv_cfg(env_dir).get("home")
    if not home:
        return None
    return Path(home) / "python.exe"


def python_version_of_env(env_dir: Path) -> str | None:
    """`3.11` usw. aus pyvenv.cfg (`version_info` bzw. `version`)."""
    cfg = read_pyvenv_cfg(env_dir)
    text = cfg.get("version_info") or cfg.get("version")
    if not text:
        return None
    parts = text.split(".")
    return ".".join(parts[:2]) if len(parts) >= 2 else None


# ---------- pip ----------

@dataclass
class PipSpec:
    """Was pip in die neue Umgebung installiert. `requirements` sind Anforderungen oder Pfade zu
    Wheels; mit `lock_file` gilt `--require-hashes` (jede Datei muss zu ihrem SHA-256 passen).
    `find_links`/`no_index`: lokaler Ordner statt bzw. neben PyPI (Freigabe, Testlauf)."""

    requirements: list[str] = field(default_factory=list)
    lock_file: Path | None = None
    find_links: list[str] = field(default_factory=list)
    no_index: bool = False
    index_url: str | None = None


def pip_install_argv(env_dir: Path, spec: PipSpec) -> list[str]:
    argv = [str(layout.venv_python(env_dir)), "-m", "pip", "install", "--disable-pip-version-check",
            "--no-input", "--no-warn-script-location", "--only-binary=:all:"]
    if spec.no_index:
        argv.append("--no-index")
    if spec.index_url:
        argv += ["--index-url", spec.index_url]
    for link in spec.find_links:
        argv += ["--find-links", str(link)]
    if spec.lock_file is not None:
        argv += ["--require-hashes", "-r", str(spec.lock_file)]
    argv += [str(r) for r in spec.requirements]
    return argv


def _tail(result: subprocess.CompletedProcess) -> str:
    text = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
    return text[-_OUTPUT_TAIL:]


def _call(run: Runner, step: str, argv: list[str], *, timeout: float, env: dict[str, str] | None = None,
          what: str) -> subprocess.CompletedProcess:
    try:
        result = run(argv, env=env if env is not None else clean_env(), timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise ProvisionError(step, _t("{what}: Zeitüberschreitung nach {timeout} s", what=what, timeout=int(timeout))) from exc
    except OSError as exc:
        raise ProvisionError(step, _t("{what}: Start fehlgeschlagen ({exc})", what=what, exc=exc)) from exc
    if result.returncode != 0:
        raise ProvisionError(step, _t("{what} fehlgeschlagen (Exit-Code {code})", what=what, code=result.returncode),
                             _tail(result))
    return result


def installed_version(env_dir: Path) -> str | None:
    """Version aus `Lib\\site-packages\\tapesmith-*.dist-info\\METADATA` der Umgebung."""
    site = Path(env_dir) / "Lib" / "site-packages"
    for info in sorted(site.glob("tapesmith-*.dist-info")):
        try:
            for line in (info / "METADATA").read_text(encoding="utf-8").splitlines():
                if line.startswith("Version:"):
                    return line.split(":", 1)[1].strip()
        except OSError:
            continue
    return None


def run_selftest(env_dir: Path, *, run: Runner = run_hidden, timeout_s: float = SELFTEST_TIMEOUT_S) -> tuple[bool, str]:
    """Selbsttest der Umgebung: `pythonw -m tapesmith.selftest --selftest-out DATEI` mit eigenem
    Temp-Datenordner (`TAPESMITH_HOME`), `QT_QPA_PLATFORM=offscreen`. Ok, wenn der Exit-Code 0 ist
    und die letzte Zeile „Selbsttest ok“ lautet. Gibt (ok, Ausgabe) zurück."""
    work = Path(tempfile.mkdtemp(prefix="tapesmith-selftest-"))
    try:
        out = work / "selftest.txt"
        env = clean_env({"QT_QPA_PLATFORM": "offscreen", "TAPESMITH_HOME": str(work / "home"),
                         "TAPESMITH_NO_DAEMON": "1"})
        argv = [str(layout.venv_python(env_dir, gui=True)), "-m", SELFTEST_MODULE, "--selftest-out", str(out)]
        try:
            result = run(argv, env=env, timeout=timeout_s)
        except (subprocess.TimeoutExpired, OSError) as exc:
            return False, type(exc).__name__
        text = out.read_text(encoding="utf-8", errors="replace") if out.exists() else ""
        lines = [line for line in text.splitlines() if line.strip()]
        ok = result.returncode == 0 and bool(lines) and lines[-1] == SELFTEST_OK
        return ok, text[-_OUTPUT_TAIL:]
    finally:
        shutil.rmtree(work, ignore_errors=True)


def write_marker(env_dir: Path, version: str, python: Path) -> Path:
    marker = Path(env_dir) / layout.VERSION_MARKER
    data = {"version": version, "python": str(python),
            "created": datetime.now(timezone.utc).replace(microsecond=0).isoformat()}
    marker.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return marker


def _normalize(version: str) -> str:
    return version.strip().lower()


def provision(root: Path, version: str, *, python: Path, spec: PipSpec, run: Runner = run_hidden,
              selftest: bool = True, log: Callable[[str], None] | None = None) -> Path:
    """Legt `versions\\<version>` als neue Umgebung an und installiert Tapesmith hinein (siehe
    Moduldoku). Vorhandener Ordner gleichen Namens wird vorher entfernt; die aktive Version darf
    der Aufrufer so nie übergeben. Bei jedem Fehler: Ordner weg, `ProvisionError`."""
    say = log or (lambda _line: None)
    target = layout.version_dir(version, root)
    if target.exists():
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        say(_t("Lege Python-Umgebung an: {target}", target=target))
        _call(run, "venv", [str(python), "-m", "venv", str(target)], timeout=VENV_TIMEOUT_S,
              what=_t("Python-Umgebung anlegen"))
        say(_t("Installiere Pakete (pip, nur Wheels)"))
        _call(run, "pip", pip_install_argv(target, spec), timeout=PIP_TIMEOUT_S, what="pip install")
        found = installed_version(target)
        if found is None or _normalize(found) != _normalize(version):
            raise ProvisionError("version", _t("In der neuen Umgebung ist Tapesmith {found} statt {version} installiert",
                                               found=found or "-", version=version))
        if selftest:
            say(_t("Selbsttest der neuen Version"))
            ok, output = run_selftest(target, run=run)
            if not ok:
                raise ProvisionError("selftest", _t("Selbsttest der Version {version} fehlgeschlagen", version=version),
                                     output)
        write_marker(target, version, python)
    except BaseException:
        shutil.rmtree(target, ignore_errors=True)
        raise
    return target
