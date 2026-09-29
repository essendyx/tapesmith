"""Gemeinsame Helfer der Update-Tests: Testschlüssel, Test-Zip, `file:`-Quelle, Installationslayout.

Nur Temp-Ordner und erzeugte Testschlüssel; nie echte Schlüssel, Netz oder Installationsordner."""

from __future__ import annotations

import subprocess
import zipfile
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tapesmith.install import installer, layout
from tapesmith.update import manifest as manifest_mod
from tapesmith.update import signing


def make_test_key() -> tuple[Ed25519PrivateKey, list]:
    private = Ed25519PrivateKey.generate()
    public = private.public_key()
    return private, [(signing.key_id(public), public)]


def make_zip(path: Path, *, exe: bytes = b"neue-exe", extra: dict[str, bytes] | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("Tapesmith/Tapesmith.exe", exe)
        zf.writestr("Tapesmith/_internal/lib.txt", b"lib")
        zf.writestr("Installieren.cmd", b"@echo off\r\n")
        for name, data in (extra or {}).items():
            zf.writestr(name, data)
    return path


def publish_dir(folder: Path, version: str, private: Ed25519PrivateKey, *, channel: str = "stable",
                notes: str = "Neu", tamper_zip: bool = False) -> Path:
    """Legt `manifest.json`, `manifest.json.sig` und das Zip in `folder` an (wie `release.py publish-dir`)."""
    folder.mkdir(parents=True, exist_ok=True)
    zip_path = make_zip(folder / f"Tapesmith-portable-{version}.zip")
    data = manifest_mod.build_manifest(zip_path, version, notes, channel, "2026-10-01T12:00:00Z")
    (folder / "manifest.json").write_bytes(data)
    (folder / "manifest.json.sig").write_text(signing.sign(data, private), encoding="ascii")
    if tamper_zip:
        with zipfile.ZipFile(zip_path, "a") as zf:
            zf.writestr("Tapesmith/boese.txt", b"x")
    return folder


def install_layout(root: Path, versions=("0.1.0",), current: str | None = None) -> Path:
    """Installationslayout in `root`: je Version `versions/<v>/Tapesmith.exe`, Junction `current` (in tmp_path)."""
    for v in versions:
        d = layout.version_dir(v, root)
        d.mkdir(parents=True, exist_ok=True)
        (d / "Tapesmith.exe").write_bytes(f"exe {v}".encode())
    order = list(versions) if current is None else [v for v in versions if v != current] + [current]
    for v in order:
        installer.activate(v, root=root)
    return root


class FakeRun:
    def __init__(self, last_line="Selbsttest ok", returncode=0, raises=None):
        self.last_line = last_line
        self.returncode = returncode
        self.raises = raises
        self.calls = []

    def __call__(self, argv, env=None, timeout=None):
        self.calls.append((argv, env, timeout))
        if self.raises is not None:
            raise self.raises
        out = Path(argv[argv.index("--selftest-out") + 1])
        out.write_text(f"Schritt 1 ok\n{self.last_line}\n", encoding="utf-8")
        return subprocess.CompletedProcess(argv, self.returncode)
