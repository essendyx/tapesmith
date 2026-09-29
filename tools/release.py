"""Release-Werkzeug für signierte Updates.

  keygen --private PFAD --public-out trusted_keys.json [--force]
  manifest --zip Z --version V --notes TEXT --out ORDNER [--channel stable|beta]
  sign --key PFAD MANIFEST
  verify --keys trusted_keys.json MANIFEST
  publish-dir --zip Z --version V --notes TEXT --key PFAD --out ORDNER [--channel stable|beta]

Der private Schlüssel ist ein Ed25519-PEM ohne Passwort, wird nur mit Rechten für den aktuellen
Benutzer geschrieben und gehört nie ins Repo (eigener Ordner für Schlüssel außerhalb des Repos).
`publish-dir` legt `manifest.json`, `manifest.json.sig` und das Zip in einen Ordner, genau wie eine
`file:`-Quelle bzw. die Assets eines GitHub-Releases sie erwarten."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from tapesmith.update import manifest as manifest_mod  # noqa: E402
from tapesmith.update import signing  # noqa: E402
from tapesmith.update.errors import UpdateError  # noqa: E402

SIG_SUFFIX = ".sig"


def restrict_to_user(path: Path) -> None:
    """Nur der aktuelle Benutzer darf die Datei lesen (icacls: Vererbung aus, Vollzugriff nur für ihn)."""
    user = os.environ.get("USERNAME") or getpass.getuser()
    subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:F"], check=True,
                   capture_output=True)


def _write_private(path: Path, pem: bytes, restrict: Callable[[Path], None]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0), 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(pem)
    restrict(path)


def _merge_public(path: Path, entry: dict) -> list[dict]:
    keys: list[dict] = []
    if path.exists():
        keys = list(json.loads(path.read_text(encoding="utf-8")).get("keys") or [])
    if not any(k.get("id") == entry["id"] for k in keys):
        keys.append(entry)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"keys": keys}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return keys


def cmd_keygen(args, out, restrict) -> int:
    private = Path(args.private)
    if private.exists() and not args.force:
        out(f"Fehler: {private} existiert bereits (überschreiben nur mit --force)")
        return 1
    pem, entry = signing.generate_keypair()
    _write_private(private, pem, restrict)
    out(f"Privater Schlüssel: {private} (nur für diesen Benutzer lesbar, nie ins Repo)")
    if args.public_out:
        keys = _merge_public(Path(args.public_out), entry)
        out(f"Öffentlicher Schlüssel {entry['id']} in {args.public_out} ({len(keys)} Schlüssel)")
    else:
        out(json.dumps(entry))
    return 0


def _write_manifest(zip_path: Path, version: str, notes: str, channel: str, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "manifest.json"
    target.write_bytes(manifest_mod.build_manifest(zip_path, version, notes, channel))
    return target


def _sign_file(manifest_path: Path, key_path: Path) -> Path:
    key = signing.load_private_key(key_path)
    sig_path = manifest_path.with_name(manifest_path.name + SIG_SUFFIX)
    sig_path.write_text(signing.sign(manifest_path.read_bytes(), key) + "\n", encoding="ascii")
    return sig_path


def _verify(manifest_path: Path, keys_path: Path, out) -> int:
    data = manifest_path.read_bytes()
    sig_path = manifest_path.with_name(manifest_path.name + SIG_SUFFIX)
    try:
        kid = signing.verify(data, sig_path.read_text(encoding="ascii"), signing.load_trusted_keys(keys_path))
        manifest = manifest_mod.parse_manifest(data)
        package = manifest_path.parent / manifest.file
        if package.exists():
            from tapesmith.update.download import verify_package

            verify_package(package, manifest)
            out(f"Paket {manifest.file}: Prüfsumme ok")
    except (UpdateError, OSError) as exc:
        out(f"Fehler: {exc}")
        return 1
    out(f"Signatur ok (Schlüssel {kid}), Version {manifest.version}, Kanal {manifest.channel}")
    return 0


def cmd_manifest(args, out, _restrict) -> int:
    target = _write_manifest(Path(args.zip), args.version, args.notes, args.channel, Path(args.out))
    out(f"Manifest: {target}")
    return 0


def cmd_sign(args, out, _restrict) -> int:
    sig = _sign_file(Path(args.manifest), Path(args.key))
    out(f"Signatur: {sig}")
    return 0


def cmd_verify(args, out, _restrict) -> int:
    return _verify(Path(args.manifest), Path(args.keys), out)


def cmd_publish_dir(args, out, _restrict) -> int:
    zip_path = Path(args.zip)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    target_zip = out_dir / zip_path.name
    if target_zip.resolve() != zip_path.resolve():
        shutil.copyfile(zip_path, target_zip)
    manifest_path = _write_manifest(target_zip, args.version, args.notes, args.channel, out_dir)
    _sign_file(manifest_path, Path(args.key))
    out(f"Veröffentlicht in {out_dir}: manifest.json, manifest.json.sig, {target_zip.name}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="release.py", description="Signierte Update-Releases für Tapesmith")
    sub = p.add_subparsers(dest="cmd", required=True)

    kg = sub.add_parser("keygen", help="Ed25519-Schlüsselpaar erzeugen")
    kg.add_argument("--private", required=True, help="Pfad des privaten Schlüssels (PEM)")
    kg.add_argument("--public-out", help="trusted_keys.json schreiben bzw. ergänzen")
    kg.add_argument("--force", action="store_true", help="vorhandenen privaten Schlüssel überschreiben")
    kg.set_defaults(func=cmd_keygen)

    for name, func, help_text in (("manifest", cmd_manifest, "manifest.json erzeugen"),
                                  ("publish-dir", cmd_publish_dir, "drei Dateien für eine file:-Quelle anlegen")):
        sp = sub.add_parser(name, help=help_text)
        sp.add_argument("--zip", required=True)
        sp.add_argument("--version", required=True)
        sp.add_argument("--notes", default="")
        sp.add_argument("--channel", choices=manifest_mod.CHANNELS, default="stable")
        sp.add_argument("--out", required=True)
        if name == "publish-dir":
            sp.add_argument("--key", required=True, help="privater Schlüssel (PEM)")
        sp.set_defaults(func=func)

    sg = sub.add_parser("sign", help="Manifest signieren (schreibt MANIFEST.sig)")
    sg.add_argument("--key", required=True)
    sg.add_argument("manifest")
    sg.set_defaults(func=cmd_sign)

    vf = sub.add_parser("verify", help="Signatur (und Prüfsumme des Zips daneben) prüfen")
    vf.add_argument("--keys", required=True, help="trusted_keys.json")
    vf.add_argument("manifest")
    vf.set_defaults(func=cmd_verify)
    return p


def main(argv: list[str] | None = None, *, out: Callable[[str], None] = print,
         restrict: Callable[[Path], None] = restrict_to_user) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args, out, restrict)
    except (OSError, ValueError, UpdateError, subprocess.CalledProcessError) as exc:
        out(f"Fehler: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
