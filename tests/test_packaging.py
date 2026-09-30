"""Paket für PyPI und Release-Workflow: Metadaten in pyproject.toml, Paketdaten im Paketordner
(sie kommen so ins Wheel), Einstieg `python -m tapesmith` und die Sicherungen im Workflow
(PyPI per Trusted Publishing, signiertes Manifest, keine EXE, kein Zip)."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

import tapesmith

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "src" / "tapesmith"
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"


@pytest.fixture(scope="module")
def pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_metadaten_vollstaendig(pyproject):
    project = pyproject["project"]
    assert project["name"] == "tapesmith"
    assert project["version"] == tapesmith.__version__
    assert project["readme"] == "README.md" and project["license"] == "MIT"
    assert project["requires-python"] == ">=3.11"
    assert len(project["description"]) > 40
    classifiers = set(project["classifiers"])
    assert {"Operating System :: Microsoft :: Windows", "Programming Language :: Python :: 3.11",
            "Programming Language :: Python :: 3.12"} <= classifiers
    urls = project["urls"]
    assert urls["Homepage"] == "https://github.com/essendyx/tapesmith" and "Issues" in urls
    for dep in project["dependencies"]:
        assert re.search(r">=\d", dep), f"Abhängigkeit ohne Untergrenze: {dep}"
    assert "pyinstaller" not in str(pyproject).lower()
    assert "gui-scripts" not in project  # keine Fenster-Starter von pip, die App startet mit pythonw -m


def test_paketdaten_liegen_im_paketordner(pyproject):
    assert pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"] == ["src/tapesmith"]
    assert (PKG / "webui" / "static" / "index.html").is_file()
    assert any((PKG / "webui" / "static" / "assets").glob("*.js"))
    assert any((PKG / "fonts").glob("*.ttf"))
    assert (PKG / "icons" / "app.ico").is_file()
    assert (PKG / "locales" / "messages" / "en.json").is_file()
    assert any((PKG / "templates").rglob("*.json"))
    assert (PKG / "update" / "trusted_keys.json").is_file()
    assert (PKG / "__main__.py").is_file()


def test_versionsnummer_ist_pep440():
    assert re.fullmatch(r"\d+(\.\d+)*((a|b|rc)\d+)?", tapesmith.__version__)


def _workflow() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_release_workflow_sicherungen():
    text = _workflow()
    assert "signpath" not in text.lower() and ".zip" not in text and "pyinstaller" not in text.lower()
    assert "build_portable" not in text and "Tapesmith.exe" not in text
    # PyPI per Trusted Publishing: OIDC-Recht nur im Job pypi, Environment pypi, keine Token-Secrets
    pypi_job = text[text.index("  pypi:"):text.index("  release:")]
    assert "id-token: write" in pypi_job and "name: pypi" in pypi_job
    assert re.search(r"pypa/gh-action-pypi-publish@[0-9a-f]{40}", pypi_job)
    assert "password" not in pypi_job and "PYPI_API_TOKEN" not in text
    assert text.count("id-token: write") == 1
    # Manifest signieren nur im Environment release mit dem Secret
    sign_job = text[text.index("  sign:"):text.index("  pypi:")]
    assert "environment: release" in sign_job and "secrets.TAPESMITH_UPDATE_SIGNING_KEY" in sign_job
    assert "tools/release.py verify" in sign_job
    # Lock-Liste für Python 3.11 und 3.12, Probeinstallation mit Prüfsummen
    assert "--wheels 3.11=wheels/py311 --wheels 3.12=wheels/py312" in text
    assert "--only-binary=:all:" in text and "--require-hashes -r out/lock.txt" in text
    # GitHub-Release erst nach PyPI, mit Manifest, Signatur, lock.txt und Wheel
    release_job = text[text.index("  release:"):]
    assert "needs: [build, sign, pypi]" in release_job
    for name in ("out/manifest.json", "out/manifest.json.sig", "out/lock.txt", "-py3-none-any.whl"):
        assert name in release_job
    # alle Actions an einen Commit gebunden
    for uses in re.findall(r"uses:\s*(\S+)", text):
        assert re.search(r"@[0-9a-f]{40}$", uses), uses


def test_release_workflow_ist_gueltiges_yaml():
    yaml = pytest.importorskip("yaml")
    data = yaml.safe_load(_workflow())
    assert set(data["jobs"]) == {"build", "sign", "pypi", "release"}
    assert data["jobs"]["pypi"]["permissions"] == {"id-token": "write"}
    assert data["jobs"]["pypi"]["environment"]["name"] == "pypi"
    assert data["jobs"]["sign"]["environment"] == "release"


def test_keine_signpath_reste():
    assert not (ROOT / ".signpath").exists()
    for rel in ("README.md", "CODE_SIGNING_POLICY.md", "docs/handbuch.md", "docs/manual.md"):
        assert "signpath" not in (ROOT / rel).read_text(encoding="utf-8").lower(), rel
