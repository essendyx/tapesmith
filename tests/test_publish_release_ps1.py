"""deploy/infra/publish-tapesmith-release.ps1 (nur Text- und Parserprüfung, nie ausführen)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy" / "infra" / "publish-tapesmith-release.ps1"
POWERSHELL = shutil.which("powershell.exe") or shutil.which("powershell")


def _text() -> str:
    return SCRIPT.read_text(encoding="utf-8-sig")


def _ps(command: str) -> subprocess.CompletedProcess:
    return subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", command],
                          capture_output=True, text=True, timeout=120)


def test_utf8_mit_bom():
    assert SCRIPT.read_bytes().startswith(b"\xef\xbb\xbf")


def test_enthaelt_alle_schritte():
    text = _text()
    for piece in (
        "[CmdletBinding(SupportsShouldProcess)]",
        "$Version", "$Notes", "$KeyPath", "$Repo", "$Prerelease",
        "[Parameter(Mandatory)][string]$KeyPath",
        "gh repo view --json nameWithOwner",
        "tools\\build_portable.py",
        "--zip",
        "tools\\release.py",
        "publish-dir",
        "manifest.json",
        "manifest.json.sig",
        "Tapesmith-portable-$Version.zip",
        "release\", \"create\"",
        "gh release view",
        "--prerelease",
        "--title",
        "--notes",
        "ShouldProcess",
        "existiert bereits",
        "Set-StrictMode",
    ):
        assert piece in text, f"fehlt: {piece}"


def test_verbotenes():
    text = _text()
    for piece in ("Invoke-Expression", "$args", "--clobber", "release delete", "git push", "BEGIN PRIVATE KEY"):
        assert piece not in text, f"verboten: {piece}"
    for dash in ("\u2013", "\u2014"):
        assert dash not in text


@pytest.mark.skipif(POWERSHELL is None, reason="powershell.exe nicht vorhanden")
def test_parser_ohne_fehler():
    path = str(SCRIPT).replace("'", "''")
    result = _ps(
        "$e=$null; [void][System.Management.Automation.Language.Parser]::ParseFile("
        f"'{path}', [ref]$null, [ref]$e); if ($e.Count) {{ $e | ForEach-Object {{ $_.Message }}; exit 1 }}"
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(POWERSHELL is None, reason="powershell.exe nicht vorhanden")
def test_get_help_nennt_parameter():
    path = str(SCRIPT).replace("'", "''")
    result = _ps(f"(Get-Help '{path}' -Full).parameters.parameter | ForEach-Object {{ $_.name }}")
    assert result.returncode == 0, result.stderr
    names = set(result.stdout.split())
    for name in ("Version", "Notes", "KeyPath", "Repo", "RepoPath", "Prerelease", "WhatIf"):
        assert name in names, result.stdout
