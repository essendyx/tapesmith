"""Paketdaten zip-/frozen-fest: Schriften und mitgelieferte Vorlagen kommen nur noch
über importlib.resources-Traversables, nie über Path(str(resources.files(...)))."""

import inspect
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from tapesmith.render.fonts import FontMissing, font_bytes, load_font
from tapesmith.templates.store import builtin_templates, find_template

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"


def test_font_bytes_reads_valid_font_data_and_rejects_unknown_font():
    assert font_bytes("sans")[:4] in (b"\x00\x01\x00\x00", b"OTTO", b"true")
    with pytest.raises(FontMissing):
        font_bytes("comic")


def test_load_font_returns_a_usable_font():
    font = load_font("sans", 20)
    bbox = font.getbbox("A")
    assert bbox is not None and bbox != (0, 0, 0, 0)


def test_no_path_str_files_outside_the_dev_only_helpers():
    for func in (load_font, builtin_templates, find_template):
        source = inspect.getsource(func)
        assert "Path(str(" not in source, f"{func.__qualname__} nutzt noch Path(str(resources.files(...))"


def test_package_works_from_a_zip_without_the_source_tree(tmp_path):
    zip_path = tmp_path / "tapesmith.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in SRC_ROOT.rglob("*"):
            if path.is_dir() or "__pycache__" in path.parts:
                continue
            zf.write(path, path.relative_to(SRC_ROOT).as_posix())

    home = tmp_path / "home"
    home.mkdir()
    code = (
        "from tapesmith.templates.store import list_templates, find_template\n"
        "from tapesmith.render.compose import LabelSpec, render_label\n"
        "from tapesmith.device.profile import load_profile\n"
        "names = [t.name for t in list_templates()]\n"
        "assert 'datentraeger' in names\n"
        "find_template('datentraeger-qr')\n"
        "r = render_label(LabelSpec(lines=('Zip',)), load_profile())\n"
        "print('OK', len(names))\n"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(zip_path)
    env["TAPESMITH_HOME"] = str(home)
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    assert proc.stdout.startswith("OK")
