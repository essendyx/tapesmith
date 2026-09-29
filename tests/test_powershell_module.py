"""Tests fuer das PowerShell-Modul deploy/powershell/Tapesmith.

Ein Teil der Tests fuehrt echtes PowerShell aus (uebersprungen, wenn powershell.exe fehlt), der
Rest prueft die Dateien nur als Text. Kein Test oeffnet einen Port oder spricht einen echten
Dienst an: das Testskript tests/ps/Tapesmith.Tests.ps1 ersetzt den HTTP-Transport per
Set-P12Transport durch einen Fake.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE_DIR = ROOT / "deploy" / "powershell" / "Tapesmith"
PSD1 = MODULE_DIR / "Tapesmith.psd1"
PSM1 = MODULE_DIR / "Tapesmith.psm1"
README = MODULE_DIR / "README.md"
PS_TEST_SCRIPT = ROOT / "tests" / "ps" / "Tapesmith.Tests.ps1"

EXPECTED_CMDLETS = sorted(
    [
        "Connect-P12",
        "Disconnect-P12",
        "Get-P12Job",
        "Get-P12Status",
        "Get-P12Template",
        "New-P12Preview",
        "Remove-P12Job",
        "Send-P12Label",
    ]
)

# Kurzendpunkte plus die bestehenden Routen, die
# das Modul ansprechen darf.
ALLOWED_ROUTES = {
    "/api/v1/status",
    "/api/v1/templates",
    "/api/v1/print",
    "/api/v1/print/text",
    "/api/v1/preview.png",
    "/api/v1/jobs",
}

_POWERSHELL = shutil.which("powershell")


def _psm1_text() -> str:
    return PSM1.read_text(encoding="utf-8-sig")


def _psd1_text() -> str:
    return PSD1.read_text(encoding="utf-8-sig")


def _run_powershell(args: list[str], *, timeout: float = 60.0, env: dict[str, str] | None = None):
    # powershell.exe schreibt auf eine umgeleitete Pipe in der Konsolen-Codepage (OEM, z. B.
    # cp850), nicht in UTF-8 und nicht in der Standard-Textcodierung von Python unter Windows
    # (cp1252): encoding/errors hier explizit setzen, sonst wirft der interne Reader-Thread von
    # subprocess bei Umlauten eine UnicodeDecodeError und result.stdout bleibt None.
    return subprocess.run(
        [_POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        env=env,
    )


@pytest.mark.skipif(_POWERSHELL is None, reason="powershell.exe nicht gefunden")
def test_module_exports_exactly_the_eight_cmdlets():
    command = (
        "$ErrorActionPreference = 'Stop'; "
        f"Import-Module '{PSD1}' -Force; "
        "(Get-Command -Module Tapesmith).Name | Sort-Object | ConvertTo-Json -Compress"
    )
    result = _run_powershell(["-Command", command])
    assert result.returncode == 0, result.stderr
    names = json.loads(result.stdout)
    if isinstance(names, str):
        names = [names]
    assert sorted(names) == EXPECTED_CMDLETS


@pytest.mark.skipif(_POWERSHELL is None, reason="powershell.exe nicht gefunden")
def test_module_manifest_is_valid():
    command = (
        "$ErrorActionPreference = 'Stop'; "
        f"Test-ModuleManifest -Path '{PSD1}' | Out-Null; "
        "Write-Output 'ok'"
    )
    result = _run_powershell(["-Command", command])
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout


@pytest.mark.skipif(_POWERSHELL is None, reason="powershell.exe nicht gefunden")
def test_ps_test_script_reports_ok():
    with tempfile.TemporaryDirectory(prefix="tapesmith-ps-pytest-") as home:
        env = dict(os.environ)
        env["TAPESMITH_HOME"] = home
        env.pop("TAPESMITH_URL", None)
        env.pop("TAPESMITH_TOKEN", None)
        result = _run_powershell(["-File", str(PS_TEST_SCRIPT)], timeout=120.0, env=env)
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        assert lines, f"kein Ausgabe von {PS_TEST_SCRIPT}: stderr={result.stderr!r}"
        payload = json.loads(lines[-1])
        if not payload.get("ok"):
            pytest.fail(
                "PowerShell-Testskript meldet Fehlschlaege: "
                + json.dumps(payload.get("failures", []), ensure_ascii=False)
            )
        assert result.returncode == 0


def test_psm1_contains_no_plaintext_token_or_user_path():
    text = _psm1_text()
    assert "C:\\Users" not in text
    lowered = text.lower()
    # 'token' selbst ist erlaubt (Parametername, Variablen), aber kein Klartext-Tokenwert der Form
    # p12_<hex>_<...> darf im Quelltext stehen.
    assert not re.search(r"p12_[0-9a-f]{8}_[A-Za-z0-9_-]{10,}", text)
    assert "bearer test" not in lowered
    assert "geheim" not in lowered or "geheimnis" not in lowered


def test_psm1_and_psd1_have_no_dash_dash_or_en_dash():
    for text in (_psm1_text(), _psd1_text()):
        assert "\u2013" not in text, "Halbgeviertstrich (\u2013) gefunden"
        assert "\u2014" not in text, "Geviertstrich (\u2014) gefunden"


def test_psm1_api_paths_are_all_contract_routes():
    text = _psm1_text()
    found = set(re.findall(r"'(/api/v1/[A-Za-z0-9_./-]*)", text))
    # Query-Strings/Platzhalter abschneiden, z. B. '/api/v1/jobs' aus Pfaden mit interpolierten
    # Teilen wie "/api/v1/jobs/$Id" landen als reiner Literal-Anteil in found.
    for path in found:
        base = path.split("?", 1)[0]
        assert any(base == route or base.startswith(route + "/") for route in ALLOWED_ROUTES), (
            f"unbekannter Pfad im Modul: {path}"
        )
    # Alle erlaubten Routen muessen tatsaechlich vorkommen.
    for route in ALLOWED_ROUTES:
        assert route in text, f"Route fehlt im Modul: {route}"


def test_psd1_and_psm1_start_with_utf8_bom():
    for path in (PSD1, PSM1):
        raw = path.read_bytes()
        assert raw.startswith(b"\xef\xbb\xbf"), f"{path.name} hat kein UTF-8-BOM"


def test_readme_exists_and_documents_local_and_lan_usage():
    text = README.read_text(encoding="utf-8-sig")
    for piece in ("Connect-P12", "Send-P12Label", "TAPESMITH_URL", "Import-Module"):
        assert piece in text, f"fehlt in README: {piece}"


def test_no_test_here_opens_a_real_port_or_service():
    # Dieser Test dokumentiert nur die Absicht: das echte Netzwerk wird nirgends in dieser Datei
    # angesprochen, tests/ps/Tapesmith.Tests.ps1 ersetzt den Transport per Set-P12Transport.
    text = PS_TEST_SCRIPT.read_text(encoding="utf-8-sig")
    assert "Set-P12Transport" in text
    assert "New-Object System.Net.Sockets" not in text
