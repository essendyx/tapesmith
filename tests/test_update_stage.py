"""Paketprüfung, Entpacken nach `versions/<v>.staging`, Selbsttest (Fake-Runner), Finalize."""

from __future__ import annotations

import subprocess
import zipfile
from pathlib import Path

import pytest

from tapesmith.install import layout
from tapesmith.update import stage
from tapesmith.update.download import verify_package
from tapesmith.update.errors import UpdateError
from tapesmith.update.manifest import parse_manifest, build_manifest
from update_fakes import FakeRun, install_layout, make_zip


def _manifest(zip_path: Path, version="0.2.1"):
    return parse_manifest(build_manifest(zip_path, version, "", "stable", "2026-10-01T12:00:00Z"))


def test_verify_package_ok_und_falsche_pruefsumme(tmp_path):
    zip_path = make_zip(tmp_path / "p.zip")
    m = _manifest(zip_path)
    assert verify_package(zip_path, m) == zip_path
    data = bytearray(zip_path.read_bytes())
    data[-1] ^= 0xFF
    zip_path.write_bytes(bytes(data))
    with pytest.raises(UpdateError) as info:
        verify_package(zip_path, m)
    assert info.value.code == "update.checksum_mismatch"
    zip_path.write_bytes(bytes(data) + b"x")
    with pytest.raises(UpdateError, match="Größe"):
        verify_package(zip_path, m)


def test_extract_gutes_zip_in_staging(tmp_path):
    root = tmp_path / "root"
    zip_path = make_zip(tmp_path / "p.zip", exe=b"EXE")
    target = stage.extract(zip_path, "0.2.1", root)
    assert target == root / "versions" / "0.2.1.staging"
    assert (target / "Tapesmith.exe").read_bytes() == b"EXE"
    assert (target / "_internal" / "lib.txt").read_bytes() == b"lib"
    assert not (target / "Installieren.cmd").exists()
    # erneutes Entpacken leert den Staging-Ordner vorher
    (target / "alt.txt").write_text("x")
    stage.extract(zip_path, "0.2.1", root)
    assert not (target / "alt.txt").exists()


@pytest.mark.parametrize("name", ["../böse.txt", "Tapesmith/../../böse.txt", "/abs.txt", "C:/win.txt",
                                  "Tapesmith\\..\\..\\x.txt"])
def test_extract_zip_slip_abgelehnt(tmp_path, name):
    zip_path = make_zip(tmp_path / "p.zip", extra={name: b"x"})
    with pytest.raises(UpdateError) as info:
        stage.extract(zip_path, "0.2.1", tmp_path / "root")
    assert info.value.code == "update.source_invalid"
    assert not (tmp_path / "böse.txt").exists()


def test_extract_ohne_exe_bzw_kein_zip(tmp_path):
    zip_path = tmp_path / "leer.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("Anderes/Tapesmith.exe", b"x")
    with pytest.raises(UpdateError, match="kein Tapesmith/Tapesmith.exe"):
        stage.extract(zip_path, "0.2.1", tmp_path / "root")
    kaputt = tmp_path / "kaputt.zip"
    kaputt.write_bytes(b"kein zip")
    with pytest.raises(UpdateError) as info:
        stage.extract(kaputt, "0.2.1", tmp_path / "root")
    assert info.value.code == "update.source_invalid"


def test_smoke_ok_und_umgebung(tmp_path):
    run = FakeRun()
    assert stage.smoke(tmp_path, run=run, timeout_s=7) is True
    argv, env, timeout = run.calls[0]
    assert argv[0] == str(tmp_path / "Tapesmith.exe")
    assert argv[1] == "--selftest"
    assert env["QT_QPA_PLATFORM"] == "offscreen"
    assert "tapesmith-update-smoke-" in env["TAPESMITH_HOME"]
    assert timeout == 7
    assert not Path(env["TAPESMITH_HOME"]).parent.exists()


@pytest.mark.parametrize("run", [
    FakeRun("Selbsttest fehlgeschlagen"),
    FakeRun(returncode=1),
    FakeRun(raises=subprocess.TimeoutExpired("x", 1)),
    FakeRun(raises=OSError("blockiert")),
])
def test_smoke_fehlgeschlagen(tmp_path, run):
    assert stage.smoke(tmp_path, run=run) is False


def test_finalize_benennt_um_und_traegt_ein(tmp_path):
    root = install_layout(tmp_path / "root", versions=("0.1.0",))
    staging = stage.extract(make_zip(tmp_path / "p.zip"), "0.2.1", root)
    target = stage.finalize(staging, "0.2.1", root)
    assert target == layout.version_dir("0.2.1", root)
    assert (target / "Tapesmith.exe").is_file()
    assert not staging.exists()
    st = layout.read_state(root)
    assert st.versions == ["0.1.0", "0.2.1"]
    assert st.current == "0.1.0"


def test_finalize_verweigert_aktive_version(tmp_path):
    root = install_layout(tmp_path / "root", versions=("0.1.0",))
    staging = stage.extract(make_zip(tmp_path / "p.zip"), "0.1.0", root)
    with pytest.raises(UpdateError):
        stage.finalize(staging, "0.1.0", root)
