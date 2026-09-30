"""Update-Manifest: Schema 2 (Lock-Liste) parsen und kanonisch erzeugen, Schema 1 weiter lesen,
Lock-Liste aus Wheel-Ordnern und `lock.txt`."""

from __future__ import annotations

import hashlib
import json

import pytest

from tapesmith.update import manifest as m
from tapesmith.update.errors import UpdateError
from update_fakes import fake_hash, legacy_manifest_bytes, lock_entries, manifest_bytes

SHA = "a" * 64


def _raw(**overrides) -> dict:
    data = json.loads(manifest_bytes("0.2.1").decode("utf-8"))
    data.update(overrides)
    return data


def _bytes(data: dict) -> bytes:
    return json.dumps(data).encode("utf-8")


def test_gueltiges_beispiel():
    parsed = m.parse_manifest(manifest_bytes("0.2.1", notes="Kurz"))
    assert parsed.kind == m.KIND_PYTHON
    assert parsed.version == "0.2.1" and parsed.channel == "stable" and parsed.notes == "Kurz"
    assert parsed.python == ("3.11", "3.12") and parsed.platform == "win_amd64"
    names = [(p.name, p.python) for p in parsed.packages]
    assert names == [("backport", "3.11"), ("pillow", None), ("tapesmith", None)]
    assert parsed.packages[1].hashes == (fake_hash("pillow-cp311"), fake_hash("pillow-cp312"))


def test_build_manifest_kanonisch_und_stabil():
    a = manifest_bytes("0.2.1")
    b = m.build_manifest("0.2.1", "Neu", list(reversed(lock_entries("0.2.1"))), python=["3.12", "3.11"],
                         published="2026-10-01T12:00:00Z")
    assert a == b
    assert a.endswith(b"\n") and json.loads(a)["schema"] == 2


def test_altes_schema_1_wird_gelesen():
    parsed = m.parse_manifest(legacy_manifest_bytes("0.2.1"))
    assert parsed.kind == m.KIND_PORTABLE and parsed.version == "0.2.1"
    assert parsed.file == "Tapesmith-portable-0.2.1.zip" and parsed.packages == ()
    with pytest.raises(ValueError):
        m.lock_text(parsed)


@pytest.mark.parametrize("change, fragment", [
    ({"schema": 3}, "Schema"),
    ({"schema": True}, "Schema"),
    ({"app": "anders"}, "App"),
    ({"version": "x.y"}, "Version"),
    ({"channel": "nightly"}, "Kanal"),
    ({"platform": "linux_x86_64"}, "Plattform"),
    ({"python": []}, "python"),
    ({"python": ["3"]}, "python"),
    ({"packages": []}, "packages"),
])
def test_ungueltige_felder(change, fragment):
    with pytest.raises(UpdateError) as info:
        m.parse_manifest(_bytes(_raw(**change)))
    assert info.value.code == "update.source_invalid"
    assert fragment in str(info.value)


@pytest.mark.parametrize("package", [
    {"name": "Pillow", "version": "1.0", "sha256": [SHA]},
    {"name": "pil low", "version": "1.0", "sha256": [SHA]},
    {"name": "pillow", "version": "1.0 --index-url x", "sha256": [SHA]},
    {"name": "pillow", "version": "1.0", "sha256": []},
    {"name": "pillow", "version": "1.0", "sha256": ["A" * 64]},
    {"name": "pillow", "version": "1.0", "sha256": [SHA], "python": "3.13"},
    {"name": "pillow", "version": "1.0", "sha256": [SHA], "python": "3.11; os_name"},
])
def test_ungueltige_pakete_werden_abgelehnt(package):
    raw = _raw()
    raw["packages"] = raw["packages"] + [package]
    with pytest.raises(UpdateError) as info:
        m.parse_manifest(_bytes(raw))
    assert info.value.code == "update.source_invalid"


def test_lock_liste_muss_tapesmith_in_der_version_enthalten():
    raw = _raw()
    raw["packages"] = [p for p in raw["packages"] if p["name"] != "tapesmith"]
    with pytest.raises(UpdateError, match="tapesmith 0.2.1"):
        m.parse_manifest(_bytes(raw))
    raw = _raw(version="0.2.2")
    with pytest.raises(UpdateError, match="tapesmith 0.2.2"):
        m.parse_manifest(_bytes(raw))


def test_kein_json():
    with pytest.raises(UpdateError):
        m.parse_manifest(b"\xff\xfe")
    with pytest.raises(UpdateError):
        m.parse_manifest(b"[]")


def test_lock_text_fuer_pip():
    text = m.lock_text(m.parse_manifest(manifest_bytes("0.2.1")))
    assert text.startswith("# Tapesmith 0.2.1 (stable), win_amd64, Python 3.11, 3.12\n")
    assert "--require-hashes --only-binary=:all: -r lock.txt" in text
    assert ("pillow==12.3.0 \\\n"
            f"    --hash=sha256:{fake_hash('pillow-cp311')} \\\n"
            f"    --hash=sha256:{fake_hash('pillow-cp312')}\n") in text
    assert f'backport==1.0 ; python_version == "3.11" \\\n    --hash=sha256:{fake_hash("backport")}\n' in text
    assert text.endswith("\n")


def test_parse_wheel_name():
    assert m.parse_wheel_name("PySide6_Essentials-6.11.2-cp39-abi3-win_amd64.whl") == \
        ("pyside6-essentials", "6.11.2", "win_amd64")
    assert m.parse_wheel_name("tapesmith-0.3.0-py3-none-any.whl") == ("tapesmith", "0.3.0", "any")
    assert m.parse_wheel_name("foo-1.0-1build-py3-none-any.whl") == ("foo", "1.0", "any")
    with pytest.raises(ValueError):
        m.parse_wheel_name("tapesmith-0.3.0.tar.gz")


def _wheel(folder, name, data):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def test_entries_from_wheels_gleiche_und_abweichende_versionen(tmp_path):
    a, b = tmp_path / "py311", tmp_path / "py312"
    t1 = _wheel(a, "tapesmith-0.3.0-py3-none-any.whl", b"t")
    _wheel(b, "tapesmith-0.3.0-py3-none-any.whl", b"t")
    p1 = _wheel(a, "pillow-12.3.0-cp311-cp311-win_amd64.whl", b"p311")
    p2 = _wheel(b, "pillow-12.3.0-cp312-cp312-win_amd64.whl", b"p312")
    x1 = _wheel(a, "numpy-2.0-cp311-cp311-win_amd64.whl", b"n311")
    x2 = _wheel(b, "numpy-2.1-cp312-cp312-win_amd64.whl", b"n312")
    only = _wheel(a, "exceptiongroup-1.2-py3-none-any.whl", b"e")
    entries = m.entries_from_wheels({"3.12": b, "3.11": a})
    got = {(e.name, e.version, e.python): e.hashes for e in entries}
    assert got[("tapesmith", "0.3.0", None)] == (t1,)
    assert got[("pillow", "12.3.0", None)] == tuple(sorted({p1, p2}))
    assert got[("numpy", "2.0", "3.11")] == (x1,) and got[("numpy", "2.1", "3.12")] == (x2,)
    assert got[("exceptiongroup", "1.2", "3.11")] == (only,)
    data = m.build_manifest("0.3.0", "", entries, python=["3.11", "3.12"])
    assert m.parse_manifest(data).version == "0.3.0"


def test_entries_from_wheels_lehnt_fremde_plattform_ab(tmp_path):
    folder = tmp_path / "py311"
    _wheel(folder, "tapesmith-0.3.0-py3-none-any.whl", b"t")
    _wheel(folder, "pillow-12.3.0-cp311-cp311-manylinux_2_17_x86_64.whl", b"p")
    with pytest.raises(ValueError, match="win_amd64"):
        m.entries_from_wheels({"3.11": folder})
    with pytest.raises(ValueError, match="Keine Wheels"):
        m.entries_from_wheels({"3.11": tmp_path / "leer"})
