"""Neue Version bereitstellen: Entpacken nach `versions\\<v>.staging`, Selbsttest der
neuen EXE, Umbenennen nach `versions\\<v>` und Eintrag in `install.json`.

Aus dem Zip zählen nur Einträge unter `Tapesmith/` (der portable Ordner); `Installieren.cmd` im
Wurzelordner wird übergangen. Absolute Pfade, Laufwerke oder `..` lehnt `extract` ab (Zip-Slip)."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import zipfile
from collections.abc import Callable
from pathlib import Path, PurePosixPath

from tapesmith.install import layout
from tapesmith.update.errors import UpdateError
from tapesmith.i18n import _t

PREFIX = "Tapesmith/"
SMOKE_TIMEOUT_S = 120
SELFTEST_OK = "Selbsttest ok"


def staging_dir(version: str, root: Path) -> Path:
    return layout.version_dir(version, root).with_name(f"{version}.staging")


def _safe_parts(name: str) -> tuple[str, ...]:
    text = name.replace("\\", "/")
    if text.startswith("/") or ":" in text:
        raise UpdateError("update.source_invalid", _t("Update-Paket enthält einen absoluten Pfad: {name!r}", name=name))
    parts = PurePosixPath(text).parts
    if any(part == ".." for part in parts):
        raise UpdateError("update.source_invalid", _t("Update-Paket enthält einen Pfad mit '..': {name!r}", name=name))
    return parts


def extract(zip_path: Path, version: str, root: Path) -> Path:
    """Entpackt den Inhalt von `Tapesmith/` nach `versions\\<v>.staging` (vorher geleert)."""
    target = staging_dir(version, root)
    try:
        with zipfile.ZipFile(zip_path) as zf:
            infos = zf.infolist()
            members = []
            for info in infos:
                parts = _safe_parts(info.filename)
                if len(parts) < 2 or parts[0] + "/" != PREFIX:
                    continue
                members.append((info, parts[1:]))
            if not any(rel == (layout.APP_EXE,) for _info, rel in members):
                raise UpdateError("update.source_invalid", _t("Update-Paket enthält kein {prefix}{app_exe}", prefix=PREFIX, app_exe=layout.APP_EXE))
            if target.exists():
                shutil.rmtree(target)
            target.mkdir(parents=True)
            for info, rel in members:
                dest = target.joinpath(*rel)
                if info.is_dir():
                    dest.mkdir(parents=True, exist_ok=True)
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, open(dest, "wb") as out:
                    shutil.copyfileobj(src, out)
    except zipfile.BadZipFile as exc:
        raise UpdateError("update.source_invalid", _t("Update-Paket ist kein gültiges Zip: {exc}", exc=exc)) from exc
    return target


def smoke(staging: Path, *, run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
          timeout_s: float = SMOKE_TIMEOUT_S) -> bool:
    """Selbsttest der neuen EXE wie `tools/build_portable.smoke_test`: eigenes Temp-`TAPESMITH_HOME`,
    `QT_QPA_PLATFORM=offscreen`, letzte Zeile der Ausgabedatei „Selbsttest ok“."""
    work = Path(tempfile.mkdtemp(prefix="tapesmith-update-smoke-"))
    try:
        out = work / "selftest.txt"
        env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "TAPESMITH_HOME": str(work / "home")}
        exe = Path(staging) / layout.APP_EXE
        try:
            result = run([str(exe), "--selftest", "--selftest-out", str(out)], env=env, timeout=timeout_s)
        except (subprocess.TimeoutExpired, OSError):
            return False
        if result.returncode != 0 or not out.exists():
            return False
        lines = [line for line in out.read_text(encoding="utf-8").splitlines() if line.strip()]
        return bool(lines) and lines[-1] == SELFTEST_OK
    finally:
        shutil.rmtree(work, ignore_errors=True)


def finalize(staging: Path, version: str, root: Path) -> Path:
    """Benennt `versions\\<v>.staging` in `versions\\<v>` um und trägt `v` in `install.json` ein."""
    state = layout.read_state(root)
    if state is not None and state.current == version:
        raise UpdateError("update.apply_failed", _t("Version {version} ist bereits aktiv", version=version))
    target = layout.version_dir(version, root)
    if target.exists():
        shutil.rmtree(target)
    os.replace(staging, target)
    state = state or layout.InstallState()
    versions = sorted(set(state.versions) | {version}, key=layout.parse_version)
    layout.write_state(layout.InstallState(current=state.current, previous=state.previous, versions=versions,
                                           failed=list(state.failed), installed_at=state.installed_at,
                                           channel=state.channel), root)
    return target
