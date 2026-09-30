"""Tests für deploy/infra/setup-tapesmith-lan.ps1 und deploy/infra/README.md.

Das Skript wird nie ausgeführt: Texttests, dazu (falls powershell.exe vorhanden) nur die
Syntaxprüfung per Parser und das Lesen der Hilfe mit Get-Help.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy" / "infra" / "setup-tapesmith-lan.ps1"
README = ROOT / "deploy" / "infra" / "README.md"
POWERSHELL = shutil.which("powershell.exe") or shutil.which("powershell")

DASHES = ("\u2013", "\u2014")


def _text() -> str:
    return SCRIPT.read_text(encoding="utf-8-sig")


def _readme() -> str:
    return README.read_text(encoding="utf-8")


def _ps(command: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True, text=True, timeout=120,
    )


def test_script_exists_with_utf8_bom():
    assert SCRIPT.read_bytes().startswith(b"\xef\xbb\xbf")


def test_script_contains_required_pieces():
    text = _text()
    for piece in (
        "[CmdletBinding(SupportsShouldProcess)]",
        "$Status",
        "$Remove",
        "192.168.0.0/16",
        "8712",
        "New-NetFirewallRule",
        "-Direction Inbound",
        "-Action Allow",
        "-Protocol TCP",
        "-RemoteAddress",
        "IsInRole",
        "ShouldProcess",
        "Set-StrictMode",
        "Tapesmith-LAN-TCP-",
        "Tapesmith Druckdienst (TCP",
        "Get-NetTCPConnection",
        "Remove-NetFirewallRule",
        "lan.enabled",
        "/health",
    ):
        assert piece in text, f"fehlt: {piece}"


def test_script_forbidden_pieces():
    text = _text()
    for piece in ("-RemoteAddress Any", "$args", "C:\\Users", "Invoke-Expression", "-Program"):
        assert piece not in text, f"verboten: {piece}"
    for dash in DASHES:
        assert dash not in text


def test_script_has_no_secrets():
    lowered = _text().lower()
    for word in ("password", "secret", "token"):
        assert word not in lowered


@pytest.mark.skipif(POWERSHELL is None, reason="powershell.exe nicht vorhanden")
def test_script_parses_without_errors():
    path = str(SCRIPT).replace("'", "''")
    result = _ps(
        "$e=$null; [void][System.Management.Automation.Language.Parser]::ParseFile("
        f"'{path}', [ref]$null, [ref]$e); if ($e.Count) {{ $e | ForEach-Object {{ $_.Message }}; exit 1 }}"
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(POWERSHELL is None, reason="powershell.exe nicht vorhanden")
def test_get_help_lists_parameters():
    path = str(SCRIPT).replace("'", "''")
    result = _ps(f"(Get-Help '{path}' -Full).parameters.parameter | ForEach-Object {{ $_.name }}")
    assert result.returncode == 0, result.stderr
    names = set(result.stdout.split())
    for name in ("Port", "RemoteAddress", "Status", "Remove"):
        assert name in names, result.stdout


README_HEADINGS = (
    "## 1. ",
    "## 2. ",
    "## 3. ",
    "## 4. ",
    "## 5. ",
    "## 6. ",
    "## 7. ",
    "## 8. ",
    "## 9. ",
    "## 10. ",
)


def test_readme_has_all_sections():
    text = _readme()
    positions = []
    for heading in README_HEADINGS:
        match = re.search("^" + re.escape(heading), text, re.MULTILINE)
        assert match, f"Abschnitt fehlt: {heading}"
        positions.append(match.start())
    assert positions == sorted(positions)


def test_readme_contains_required_pieces():
    text = _readme()
    for piece in (
        "setup-tapesmith-lan.ps1",
        "release.yml",
        "lan.enabled",
        "p12 token add",
        "Uptime",
        "COM-Blockade",
        "guard.confirm_copies",
        "-Remove",
        "-Status",
        "deploy/homeassistant/README.md",
        "deploy/powershell/Tapesmith/README.md",
    ):
        assert piece in text, f"fehlt: {piece}"


def test_readme_has_no_dashes_or_tokens():
    text = _readme()
    for dash in DASHES:
        assert dash not in text
    assert " - " not in text.replace("\n- ", "\n")
    assert not re.search(r"p12_[0-9a-f]{8}_", text)
