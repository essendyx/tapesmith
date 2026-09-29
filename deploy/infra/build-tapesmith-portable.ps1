<#
.SYNOPSIS
  Baut die portable Tapesmith-App (PyInstaller onedir, kein Onefile) und prueft sie per Selbsttest.
  Build-Logik: <Repo>\tools\build_portable.py im App-Repo (Standard: zwei Ebenen über diesem Skript).
  Idempotent: PyInstaller baut mit --clean/--noconfirm neu nach <Repo>\dist\Tapesmith.
#>
param(
  [string]$Repo = (Join-Path $PSScriptRoot "..\.."),
  [switch]$NoZip,
  [ValidateSet("pyinstaller", "nuitka")][string]$Backend = "pyinstaller"
)
$ErrorActionPreference = "Stop"
$py = Join-Path $Repo ".venv\Scripts\python.exe"
$buildScript = Join-Path $Repo "tools\build_portable.py"
if (-not (Test-Path $py))          { Write-Error "venv fehlt: $py (erst Setup ausführen)"; exit 1 }
if (-not (Test-Path $buildScript)) { Write-Error "Build-Skript fehlt: $buildScript"; exit 1 }
$buildArgs = @($buildScript, "--backend", $Backend)
if (-not $NoZip) { $buildArgs += "--zip" }
& $py @buildArgs
exit $LASTEXITCODE
