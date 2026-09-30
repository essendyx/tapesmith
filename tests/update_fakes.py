"""Gemeinsame Helfer der Installations- und Update-Tests: Testschlüssel, signierte Python-Manifeste,
`file:`-Quelle, Installationslayout mit Versionsumgebungen und ein Fake für venv, pip und Selbsttest.

Nur Temp-Ordner und erzeugte Testschlüssel; nie echte Schlüssel, Netz, pip oder Installationsordner."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tapesmith.install import installer, layout
from tapesmith.update import manifest as manifest_mod
from tapesmith.update import signing

PYTHON = Path("C:/Fake/Python311/python.exe")


def make_test_key() -> tuple[Ed25519PrivateKey, list]:
    private = Ed25519PrivateKey.generate()
    public = private.public_key()
    return private, [(signing.key_id(public), public)]


def fake_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def lock_entries(version: str, python: tuple[str, ...] = ("3.11", "3.12")) -> list[manifest_mod.LockEntry]:
    """Kleine, aber vollständige Lock-Liste: Tapesmith, ein natives Paket mit zwei Wheels und eine
    Abhängigkeit nur für Python 3.11."""
    return [
        manifest_mod.LockEntry("tapesmith", version, (fake_hash(f"tapesmith-{version}"),)),
        manifest_mod.LockEntry("pillow", "12.3.0", (fake_hash("pillow-cp311"), fake_hash("pillow-cp312"))),
        *([manifest_mod.LockEntry("backport", "1.0", (fake_hash("backport"),), python="3.11")] if "3.11" in python else []),
    ]


def manifest_bytes(version: str, *, channel: str = "stable", notes: str = "Neu",
                   python: tuple[str, ...] = ("3.11", "3.12")) -> bytes:
    return manifest_mod.build_manifest(version, notes, lock_entries(version, python), python=python, channel=channel,
                                       published="2026-10-01T12:00:00Z")


def publish_dir(folder: Path, version: str, private: Ed25519PrivateKey, *, channel: str = "stable",
                notes: str = "Neu", python: tuple[str, ...] = ("3.11", "3.12"), wheels: bool = False,
                data: bytes | None = None) -> Path:
    """Legt `manifest.json`, `manifest.json.sig` und `lock.txt` in `folder` an (wie
    `release.py publish-dir`); mit `wheels` zusätzlich einen Ordner `wheels` mit einer Datei."""
    folder.mkdir(parents=True, exist_ok=True)
    data = data if data is not None else manifest_bytes(version, channel=channel, notes=notes, python=python)
    (folder / "manifest.json").write_bytes(data)
    (folder / "manifest.json.sig").write_text(signing.sign(data, private), encoding="ascii")
    parsed = manifest_mod.parse_manifest(data)
    if parsed.kind == manifest_mod.KIND_PYTHON:
        (folder / "lock.txt").write_text(manifest_mod.lock_text(parsed), encoding="utf-8")
    if wheels:
        (folder / "wheels").mkdir(exist_ok=True)
        (folder / "wheels" / f"tapesmith-{version}-py3-none-any.whl").write_bytes(b"wheel")
    return folder


def legacy_manifest_bytes(version: str) -> bytes:
    """Manifest im früheren Schema 1 (portabler Build, Zip)."""
    import json

    data = {"schema": 1, "app": "tapesmith", "version": version, "channel": "stable",
            "published": "2026-10-01T12:00:00Z", "notes": "alt",
            "package": {"file": f"Tapesmith-portable-{version}.zip", "sha256": "a" * 64, "size": 10}}
    return (json.dumps(data, indent=2, sort_keys=True) + "\n").encode("utf-8")


def make_version(root: Path, version: str, *, python: Path = PYTHON, python_version: str = "3.11.9") -> Path:
    """Fertige Versionsumgebung `versions/<v>` wie nach `venv.provision` (ohne echtes Python)."""
    target = layout.version_dir(version, root)
    (target / "Scripts").mkdir(parents=True, exist_ok=True)
    for name in ("python.exe", "pythonw.exe"):
        (target / "Scripts" / name).write_bytes(b"starter")
    (target / "pyvenv.cfg").write_text(f"home = {python.parent}\nversion_info = {python_version}\n", encoding="utf-8")
    dist = target / "Lib" / "site-packages" / f"tapesmith-{version}.dist-info"
    dist.mkdir(parents=True, exist_ok=True)
    (dist / "METADATA").write_text(f"Metadata-Version: 2.4\nName: tapesmith\nVersion: {version}\n", encoding="utf-8")
    (target / layout.VERSION_MARKER).write_text("{}", encoding="utf-8")
    return target


def make_frozen_version(root: Path, version: str, content: bytes = b"exe") -> Path:
    """Versionsordner des früheren portablen Builds (`Tapesmith.exe`)."""
    target = layout.version_dir(version, root)
    target.mkdir(parents=True, exist_ok=True)
    (target / layout.APP_EXE).write_bytes(content)
    (target / "_internal").mkdir(exist_ok=True)
    return target


def install_layout(root: Path, versions=("0.1.0",), current: str | None = None) -> Path:
    """Installationslayout in `root`: je Version eine Versionsumgebung, Junction `current`."""
    for v in versions:
        make_version(root, v)
    order = list(versions) if current is None else [v for v in versions if v != current] + [current]
    for v in order:
        installer.activate(v, root=root)
    return root


def _version_from_lock(text: str) -> str | None:
    for line in text.splitlines():
        if line.startswith("tapesmith=="):
            return line.split("==", 1)[1].split()[0]
    return None


class FakeVenvRun:
    """Ersetzt `install.venv.run_hidden`: `python -m venv ZIEL` legt eine Umgebung an,
    `… -m pip install …` schreibt die dist-info der angeforderten Tapesmith-Version, der Selbsttest
    schreibt seine Ausgabedatei. Alle Aufrufe stehen in `calls`, Lock-Listen in `locks`."""

    def __init__(self, *, selftest_ok: bool = True, pip_rc: int = 0, venv_rc: int = 0,
                 installed_version: str | None = None, python_version: str = "3.11.9",
                 raises: BaseException | None = None,
                 pip_error: str = "ERROR: Could not find a version that satisfies the requirement"):
        self.selftest_ok = selftest_ok
        self.pip_rc = pip_rc
        self.venv_rc = venv_rc
        self.installed_version = installed_version
        self.python_version = python_version
        self.raises = raises
        self.pip_error = pip_error
        self.calls: list[tuple[list[str], dict | None, float | None]] = []
        self.locks: list[str] = []

    def kinds(self) -> list[str]:
        result = []
        for argv, _env, _timeout in self.calls:
            if argv[1:3] == ["-m", "venv"]:
                result.append("venv")
            elif argv[1:4] == ["-m", "pip", "install"]:
                result.append("pip")
            else:
                result.append("selftest")
        return result

    def __call__(self, argv, env=None, timeout=None):
        argv = [str(a) for a in argv]
        self.calls.append((argv, env, timeout))
        if self.raises is not None:
            raise self.raises
        if argv[1:3] == ["-m", "venv"]:
            target = Path(argv[3])
            if self.venv_rc == 0:
                (target / "Scripts").mkdir(parents=True, exist_ok=True)
                for name in ("python.exe", "pythonw.exe"):
                    (target / "Scripts" / name).write_bytes(b"starter")
                (target / "pyvenv.cfg").write_text(
                    f"home = {Path(argv[0]).parent}\nversion_info = {self.python_version}\n", encoding="utf-8")
            return subprocess.CompletedProcess(argv, self.venv_rc, "", "venv kaputt" if self.venv_rc else "")
        if argv[1:4] == ["-m", "pip", "install"]:
            env_dir = Path(argv[0]).parent.parent
            version = self.installed_version
            if "-r" in argv:
                text = Path(argv[argv.index("-r") + 1]).read_text(encoding="utf-8")
                self.locks.append(text)
                version = version or _version_from_lock(text)
            for arg in argv:
                if arg.startswith("tapesmith=="):
                    version = version or arg.split("==", 1)[1]
                elif arg.endswith(".whl") and Path(arg).name.startswith("tapesmith-"):
                    version = version or Path(arg).name.split("-")[1]
            if self.pip_rc == 0 and version:
                dist = env_dir / "Lib" / "site-packages" / f"tapesmith-{version}.dist-info"
                dist.mkdir(parents=True, exist_ok=True)
                (dist / "METADATA").write_text(f"Metadata-Version: 2.4\nName: tapesmith\nVersion: {version}\n",
                                               encoding="utf-8")
            return subprocess.CompletedProcess(argv, self.pip_rc, "", self.pip_error if self.pip_rc else "")
        if "-m" in argv and argv[argv.index("-m") + 1] == "tapesmith.selftest":
            out = Path(argv[argv.index("--selftest-out") + 1])
            last = "Selbsttest ok" if self.selftest_ok else "Selbsttest fehlgeschlagen"
            out.write_text(f"OK Schritt: fein\n{last}\n", encoding="utf-8")
            return subprocess.CompletedProcess(argv, 0 if self.selftest_ok else 1, "", "")
        raise AssertionError(f"unerwarteter Aufruf: {argv}")
