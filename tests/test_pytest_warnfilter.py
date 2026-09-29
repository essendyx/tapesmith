"""Die Suite sammelt auch mit `pytest -W error` (Starlette warnt beim Import des TestClients)."""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_sammeln_mit_w_error_klappt_fuer_webapi_tests():
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    env.pop("PYTEST_CURRENT_TEST", None)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-W", "error", "--co",
         "tests/test_webapi_tools.py", "tests/test_webapi_security.py"],
        cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
    )
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-2000:]
