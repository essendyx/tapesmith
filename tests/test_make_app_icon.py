"""Tests für `tools/make_app_icon.py`: erzeugt `app.ico` in einen Temp-Pfad mit allen
`ICON_SIZES`, `--check` vergleicht mit der eingecheckten Datei."""

import importlib.util
from pathlib import Path

from PIL import Image

TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
CHECKED_IN = Path(__file__).resolve().parent.parent / "src" / "tapesmith" / "icons" / "app.ico"


def _load_module():
    spec = importlib.util.spec_from_file_location("make_app_icon_test_mod", TOOLS_DIR / "make_app_icon.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_erzeugt_ico_mit_acht_groessen(tmp_path):
    module = _load_module()
    out = tmp_path / "app.ico"
    code = module.main(["--out", str(out)])
    assert code == 0
    assert out.exists()
    with Image.open(out) as image:
        sizes = set(image.info["sizes"])
    assert sizes == {(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48), (64, 64), (256, 256)}


def test_check_gegen_eingecheckte_datei_exit_0():
    module = _load_module()
    assert CHECKED_IN.exists(), "app.ico fehlt, bitte tools/make_app_icon.py ausführen"
    code = module.main(["--out", str(CHECKED_IN), "--check"])
    assert code == 0


def test_check_meldet_abweichung(tmp_path):
    module = _load_module()
    out = tmp_path / "app.ico"
    out.write_bytes(b"nicht das erwartete ico")
    code = module.main(["--out", str(out), "--check"])
    assert code == 1


def test_check_meldet_fehlende_datei(tmp_path):
    module = _load_module()
    out = tmp_path / "fehlt.ico"
    code = module.main(["--out", str(out), "--check"])
    assert code == 1
