"""Tests für deploy/infra/build-tapesmith-portable.ps1 (Aufrufer fürs Infra-Repo).

Liest die Datei nur als Text, führt kein PowerShell aus.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy" / "infra" / "build-tapesmith-portable.ps1"


def _text() -> str:
    return SCRIPT.read_text(encoding="utf-8-sig")


def test_script_exists_and_contains_required_pieces():
    text = _text()
    for piece in (
        "tools\\build_portable.py",
        "--zip",
        "--backend",
        ".venv\\Scripts\\python.exe",
        "exit $LASTEXITCODE",
        "[switch]$NoZip",
    ):
        assert piece in text, f"fehlt: {piece}"


def test_script_never_onefile_or_args_variable():
    text = _text()
    assert "--onefile" not in text
    assert "$args" not in text


def test_script_has_no_secrets_or_hardcoded_user_path():
    text = _text()
    assert "C:\\Users" not in text
    lowered = text.lower()
    for secret_word in ("token", "password", "secret"):
        assert secret_word not in lowered
