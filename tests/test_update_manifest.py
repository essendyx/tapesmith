"""Update-Manifest parsen und kanonisch erzeugen."""

from __future__ import annotations

import hashlib
import json

import pytest

from tapesmith.update.errors import UpdateError
from tapesmith.update.manifest import Manifest, build_manifest, parse_manifest
from update_fakes import make_zip

SHA = "a" * 64


def _raw(**overrides) -> dict:
    data = {"schema": 1, "app": "tapesmith", "version": "0.2.1", "channel": "stable",
            "published": "2026-10-01T12:00:00Z", "notes": "Kurzbeschreibung",
            "package": {"file": "Tapesmith-portable-0.2.1.zip", "sha256": SHA, "size": 123456}}
    data.update(overrides)
    return data


def _bytes(data: dict) -> bytes:
    return json.dumps(data).encode("utf-8")


def test_gueltiges_beispiel():
    m = parse_manifest(_bytes(_raw()))
    assert m == Manifest(version="0.2.1", channel="stable", published="2026-10-01T12:00:00Z",
                         notes="Kurzbeschreibung", file="Tapesmith-portable-0.2.1.zip", sha256=SHA, size=123456)


@pytest.mark.parametrize("data", [
    {k: v for k, v in _raw().items() if k != "version"},
    {k: v for k, v in _raw().items() if k != "package"},
    _raw(app="anderes"),
    _raw(schema=2),
    _raw(version="kaputt!"),
    _raw(channel="nightly"),
    _raw(package={"file": "../boese.zip", "sha256": SHA, "size": 1}),
    _raw(package={"file": "sub/x.zip", "sha256": SHA, "size": 1}),
    _raw(package={"file": "x.zip", "sha256": "xyz", "size": 1}),
    _raw(package={"file": "x.zip", "sha256": SHA, "size": 0}),
    _raw(package={"file": "x.zip", "sha256": SHA}),
])
def test_ungueltig_source_invalid(data):
    with pytest.raises(UpdateError) as info:
        parse_manifest(_bytes(data))
    assert info.value.code == "update.source_invalid"


def test_kein_json():
    with pytest.raises(UpdateError) as info:
        parse_manifest(b"\xff\xfe nicht json")
    assert info.value.code == "update.source_invalid"
    with pytest.raises(UpdateError):
        parse_manifest(b"[1, 2]")


def test_build_manifest_kanonisch(tmp_path):
    zip_path = make_zip(tmp_path / "Tapesmith-portable-0.2.1.zip")
    data = build_manifest(zip_path, "0.2.1", "Grüße", "beta", "2026-10-01T12:00:00Z")
    assert data.endswith(b"}\n")
    raw = json.loads(data)
    assert list(raw) == sorted(raw)
    assert raw["package"]["sha256"] == hashlib.sha256(zip_path.read_bytes()).hexdigest()
    assert raw["package"]["size"] == zip_path.stat().st_size
    assert "Grüße".encode() in data
    m = parse_manifest(data)
    assert (m.version, m.channel, m.notes, m.file) == ("0.2.1", "beta", "Grüße", zip_path.name)
    assert build_manifest(zip_path, "0.2.1", "Grüße", "beta", "2026-10-01T12:00:00Z") == data


def test_build_manifest_standardzeit_und_fehler(tmp_path):
    zip_path = make_zip(tmp_path / "p.zip")
    raw = json.loads(build_manifest(zip_path, "0.3.0", ""))
    assert raw["published"].endswith("Z")
    with pytest.raises(ValueError):
        build_manifest(zip_path, "0.3.0", "", "nightly")
    with pytest.raises(ValueError):
        build_manifest(zip_path, "nix", "")
