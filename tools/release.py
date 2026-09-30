"""Release-Werkzeug für signierte Updates (Verteilung über Python).

  keygen --private PFAD --public-out trusted_keys.json [--force]
  manifest --version V --wheels 3.11=ORDNER --wheels 3.12=ORDNER --out ORDNER [--notes TEXT] [--channel stable|beta]
  sign --key PFAD MANIFEST
  verify --keys trusted_keys.json MANIFEST
  publish-dir --version V --wheels 3.11=ORDNER ... --key PFAD --out ORDNER [--notes TEXT] [--channel ...] [--copy-wheels]

`--wheels PY=ORDNER`: Ordner mit allen Wheels, die `pip download --only-binary=:all:` für diese
Python-Version geladen hat (Tapesmith selbst und alle Abhängigkeiten, `win_amd64` bzw. `any`).
Daraus entsteht die Lock-Liste (Name, Version, SHA-256 je Wheel) im Manifest und als `lock.txt`.

Der private Schlüssel ist ein Ed25519-PEM ohne Passwort, wird nur mit Rechten für den aktuellen
Benutzer geschrieben und gehört nie ins Repo (eigener Ordner für Schlüssel außerhalb des Repos).
`publish-dir` legt `manifest.json`, `manifest.json.sig` und `lock.txt` in einen Ordner, genau wie
die Assets eines GitHub-Releases; mit `--copy-wheels` zusätzlich alle Wheels unter `wheels/`, so
wird der Ordner eine vollständige `file:`-Quelle ohne PyPI (Freigabe im Firmennetz, Testlauf)."""

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


def parse_wheel_dirs(values: list[str]) -> dict[str, Path]:
    """`["3.11=a", "3.12=b"]` zu `{"3.11": Path("a"), ...}`."""
    result: dict[str, Path] = {}
    for value in values:
        py, sep, folder = value.partition("=")
        if not sep or not py.strip() or not folder.strip():
            raise ValueError(f"--wheels erwartet PY=ORDNER, bekommen: {value!r}")
        if py.strip() in result:
            raise ValueError(f"Python {py.strip()} doppelt angegeben")
        result[py.strip()] = Path(folder.strip())
    if not result:
        raise ValueError("mindestens ein --wheels PY=ORDNER nötig")
    return result


def _write_manifest(args, out_dir: Path) -> tuple[Path, manifest_mod.Manifest]:
    dirs = parse_wheel_dirs(args.wheels)
    entries = manifest_mod.entries_from_wheels(dirs)
    data = manifest_mod.build_manifest(args.version, args.notes, entries, python=dirs.keys(), channel=args.channel)
    parsed = manifest_mod.parse_manifest(data)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "manifest.json"
    target.write_bytes(data)
    (out_dir / manifest_mod.LOCK_NAME).write_text(manifest_mod.lock_text(parsed), encoding="utf-8")
    return target, parsed


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
        lock = manifest_path.parent / manifest_mod.LOCK_NAME
        if manifest.kind == manifest_mod.KIND_PYTHON and lock.exists():
            if lock.read_text(encoding="utf-8") != manifest_mod.lock_text(manifest):
                out("Fehler: lock.txt passt nicht zum Manifest")
                return 1
            out("lock.txt passt zum Manifest")
    except (UpdateError, OSError) as exc:
        out(f"Fehler: {exc}")
        return 1
    out(f"Signatur ok (Schlüssel {kid}), Version {manifest.version}, Kanal {manifest.channel}, "
        f"{len(manifest.packages)} Pakete, Python {', '.join(manifest.python) or '-'}")
    return 0


def cmd_manifest(args, out, _restrict) -> int:
    target, parsed = _write_manifest(args, Path(args.out))
    out(f"Manifest: {target} ({len(parsed.packages)} Pakete), lock.txt daneben")
    return 0


def cmd_sign(args, out, _restrict) -> int:
    sig = _sign_file(Path(args.manifest), Path(args.key))
    out(f"Signatur: {sig}")
    return 0


def cmd_verify(args, out, _restrict) -> int:
    return _verify(Path(args.manifest), Path(args.keys), out)


def cmd_publish_dir(args, out, _restrict) -> int:
    out_dir = Path(args.out)
    manifest_path, _parsed = _write_manifest(args, out_dir)
    _sign_file(manifest_path, Path(args.key))
    names = ["manifest.json", "manifest.json.sig", manifest_mod.LOCK_NAME]
    if args.copy_wheels:
        wheels = out_dir / "wheels"
        wheels.mkdir(parents=True, exist_ok=True)
        for folder in parse_wheel_dirs(args.wheels).values():
            for wheel in sorted(Path(folder).glob("*.whl")):
                target = wheels / wheel.name
                if not target.exists():
                    shutil.copyfile(wheel, target)
        names.append("wheels/")
    out(f"Veröffentlicht in {out_dir}: {', '.join(names)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="release.py", description="Signierte Update-Releases für Tapesmith")
    sub = p.add_subparsers(dest="cmd", required=True)

    kg = sub.add_parser("keygen", help="Ed25519-Schlüsselpaar erzeugen")
    kg.add_argument("--private", required=True, help="Pfad des privaten Schlüssels (PEM)")
    kg.add_argument("--public-out", help="trusted_keys.json schreiben bzw. ergänzen")
    kg.add_argument("--force", action="store_true", help="vorhandenen privaten Schlüssel überschreiben")
    kg.set_defaults(func=cmd_keygen)

    for name, func, help_text in (("manifest", cmd_manifest, "manifest.json und lock.txt erzeugen"),
                                  ("publish-dir", cmd_publish_dir, "signierte Release-Dateien in einen Ordner legen")):
        sp = sub.add_parser(name, help=help_text)
        sp.add_argument("--version", required=True)
        sp.add_argument("--wheels", action="append", default=[], required=True, metavar="PY=ORDNER",
                        help="Wheels für eine Python-Version, z. B. 3.11=wheels/py311 (mehrfach)")
        sp.add_argument("--notes", default="")
        sp.add_argument("--channel", choices=manifest_mod.CHANNELS, default="stable")
        sp.add_argument("--out", required=True)
        if name == "publish-dir":
            sp.add_argument("--key", required=True, help="privater Schlüssel (PEM)")
            sp.add_argument("--copy-wheels", action="store_true", help="Wheels nach <out>/wheels kopieren (file:-Quelle ohne PyPI)")
        sp.set_defaults(func=func)

    sg = sub.add_parser("sign", help="Manifest signieren (schreibt MANIFEST.sig)")
    sg.add_argument("--key", required=True)
    sg.add_argument("manifest")
    sg.set_defaults(func=cmd_sign)

    vf = sub.add_parser("verify", help="Signatur (und lock.txt daneben) prüfen")
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
