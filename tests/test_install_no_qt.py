"""Stellt sicher, dass `tapesmith.install` (Installer) kein PySide6/Qt importiert.

`tests/test_no_qt_in_core.py` pflegt die gemeinsame Liste; dieser Test prüft dasselbe
eigenständig nur für die Installationsmodule."""

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

INSTALL_MODULES = [
    "tapesmith.install",
    "tapesmith.install.layout",
    "tapesmith.install.junction",
    "tapesmith.install.processes",
    "tapesmith.install.shortcuts",
    "tapesmith.install.registry",
    "tapesmith.install.installer",
    "tapesmith.install.uninstaller",
    "tapesmith.cli_cmds.install",
]


def test_install_module_importiert_kein_qt():
    imports = "\n".join(f"import {name}" for name in INSTALL_MODULES)
    code = f"{imports}\nimport sys\nprint('PySide6' in sys.modules)\n"

    env = dict(os.environ)
    src_path = str(REPO_ROOT / "src")
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = src_path if not existing else os.pathsep.join([src_path, existing])
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    env.pop("TAPESMITH_INSTALL_ROOT", None)
    env.pop("TAPESMITH_START_MENU_DIR", None)

    result = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip() == "False", result.stdout + result.stderr
