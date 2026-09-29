"""`tools/release.py` (keygen, manifest, sign, verify, publish-dir) nur mit Testschlüsseln in tmp_path."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from tapesmith.update import signing
from tapesmith.update.manifest import parse_manifest
from tapesmith.update.sources import FileSource
from update_fakes import make_zip

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "release.py"


@pytest.fixture(scope="module")
def release():
    spec = importlib.util.spec_from_file_location("release_tool", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class Out:
    def __init__(self):
        self.lines: list[str] = []

    def __call__(self, text):
        self.lines.append(text)

    @property
    def text(self):
        return "\n".join(self.lines)


def _run(release, argv):
    out = Out()
    restricted: list[Path] = []
    rc = release.main(argv, out=out, restrict=restricted.append)
    return rc, out, restricted


def test_keygen_schreibt_privat_und_trusted_keys(release, tmp_path):
    private = tmp_path / "keys" / "signing.pem"
    public = tmp_path / "trusted_keys.json"
    rc, out, restricted = _run(release, ["keygen", "--private", str(private), "--public-out", str(public)])
    assert rc == 0, out.text
    assert private.read_bytes().startswith(b"-----BEGIN PRIVATE KEY-----")
    assert restricted == [private]
    keys = json.loads(public.read_text(encoding="utf-8"))["keys"]
    assert len(keys) == 1 and len(keys[0]["id"]) == 16
    assert signing.load_trusted_keys(public)[0][0] == keys[0]["id"]
    assert "nie ins Repo" in out.text


def test_keygen_ohne_force_verweigert_ueberschreiben(release, tmp_path):
    private = tmp_path / "signing.pem"
    private.write_bytes(b"alt")
    rc, out, restricted = _run(release, ["keygen", "--private", str(private)])
    assert rc == 1
    assert "--force" in out.text
    assert private.read_bytes() == b"alt"
    assert restricted == []
    rc, _out, _r = _run(release, ["keygen", "--private", str(private), "--force"])
    assert rc == 0
    assert private.read_bytes() != b"alt"


def test_keygen_ergaenzt_vorhandene_schluessel(release, tmp_path):
    public = tmp_path / "trusted_keys.json"
    public.write_text('{"keys": []}\n', encoding="utf-8")
    for name in ("a.pem", "b.pem"):
        assert _run(release, ["keygen", "--private", str(tmp_path / name), "--public-out", str(public)])[0] == 0
    assert len(json.loads(public.read_text(encoding="utf-8"))["keys"]) == 2


def test_publish_dir_und_verify(release, tmp_path):
    private = tmp_path / "signing.pem"
    public = tmp_path / "trusted_keys.json"
    _run(release, ["keygen", "--private", str(private), "--public-out", str(public)])
    zip_path = make_zip(tmp_path / "dist" / "Tapesmith-portable-0.2.1.zip")
    out_dir = tmp_path / "feed"
    rc, out, _r = _run(release, ["publish-dir", "--zip", str(zip_path), "--version", "0.2.1", "--notes",
                                 "Neu", "--key", str(private), "--out", str(out_dir)])
    assert rc == 0, out.text
    assert sorted(p.name for p in out_dir.iterdir()) == ["Tapesmith-portable-0.2.1.zip", "manifest.json",
                                                         "manifest.json.sig"]
    rc, out, _r = _run(release, ["verify", "--keys", str(public), str(out_dir / "manifest.json")])
    assert rc == 0, out.text
    assert "Signatur ok" in out.text and "Prüfsumme ok" in out.text
    # die file:-Quelle liest genau diese drei Dateien
    data, sig = FileSource(out_dir).fetch_manifest()
    signing.verify(data, sig, signing.load_trusted_keys(public))
    assert parse_manifest(data).version == "0.2.1"


def test_manifest_sign_verify_einzeln_und_manipulation(release, tmp_path):
    private = tmp_path / "signing.pem"
    public = tmp_path / "trusted_keys.json"
    _run(release, ["keygen", "--private", str(private), "--public-out", str(public)])
    zip_path = make_zip(tmp_path / "feed" / "Tapesmith-portable-0.3.0-beta.1.zip")
    rc, _o, _r = _run(release, ["manifest", "--zip", str(zip_path), "--version", "0.3.0-beta.1", "--channel",
                                "beta", "--out", str(tmp_path / "feed")])
    assert rc == 0
    manifest = tmp_path / "feed" / "manifest.json"
    assert _run(release, ["sign", "--key", str(private), str(manifest)])[0] == 0
    assert _run(release, ["verify", "--keys", str(public), str(manifest)])[0] == 0
    manifest.write_bytes(manifest.read_bytes().replace(b"beta", b"stable", 1))
    rc, out, _r = _run(release, ["verify", "--keys", str(public), str(manifest)])
    assert rc == 1 and "Signatur" in out.text


def test_verify_ohne_schluessel_und_fehlende_datei(release, tmp_path):
    empty = tmp_path / "trusted_keys.json"
    empty.write_text('{"keys": []}', encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_bytes(b"{}")
    (tmp_path / "manifest.json.sig").write_text("AAAA", encoding="ascii")
    rc, out, _r = _run(release, ["verify", "--keys", str(empty), str(manifest)])
    assert rc == 1 and "Kein vertrauenswürdiger" in out.text
    rc, out, _r = _run(release, ["sign", "--key", str(tmp_path / "fehlt.pem"), str(manifest)])
    assert rc == 1 and out.text.startswith("Fehler")
