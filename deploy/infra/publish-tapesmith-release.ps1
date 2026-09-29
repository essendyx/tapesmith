<#
.SYNOPSIS
  Baut, signiert und veroeffentlicht ein Update-Release von Tapesmith als GitHub-Release.
.DESCRIPTION
  Schritte:
    1. Portablen Build mit Zip erzeugen: <RepoPath>\tools\build_portable.py --zip
       (Ergebnis <RepoPath>\dist\Tapesmith-portable-<Version>.zip; Version kommt aus src\tapesmith\__init__.py).
    2. Signierte Release-Dateien in einen Temp-Ordner legen: tools\release.py publish-dir
       (manifest.json, manifest.json.sig, Tapesmith-portable-<Version>.zip).
    3. gh release create v<Version> <3 Dateien> --repo <Repo> --title ... --notes ...
  Idempotent: existiert das Release v<Version> schon, bricht das Skript mit Hinweis ab.
  Mit -WhatIf werden die Befehle nur ausgegeben (kein Build, keine Signatur, kein Upload).
  Der private Signaturschluessel liegt nur unter -KeyPath (nie im Repo).
.PARAMETER Version
  Versionsnummer ohne v, muss zu src\tapesmith\__init__.py passen (z. B. 0.3.1).
.PARAMETER Notes
  Kurzbeschreibung fuer Manifest und Release.
.PARAMETER KeyPath
  Privater Ed25519-Schluessel (PEM), erzeugt mit tools\release.py keygen.
.PARAMETER Repo
  GitHub-Repository owner/name. Ohne Angabe: das Repository des lokalen Checkouts (gh repo view).
.PARAMETER RepoPath
  Lokaler Checkout des App-Repos mit .venv. Standard: zwei Ebenen über diesem Skript.
.PARAMETER Prerelease
  Als Vorabversion veroeffentlichen (Kanal beta).
.EXAMPLE
  .\publish-tapesmith-release.ps1 -Version 0.3.1 -Notes "Fehlerbehebungen" -KeyPath D:\keys\tapesmith_signing.pem -WhatIf
#>
[CmdletBinding(SupportsShouldProcess)]
param(
  [Parameter(Mandatory)][ValidatePattern('^\d+(\.\d+)*(-[A-Za-z0-9.]+)?$')][string]$Version,
  [Parameter(Mandatory)][string]$Notes,
  [Parameter(Mandatory)][string]$KeyPath,
  [string]$Repo = "",
  [string]$RepoPath = (Join-Path $PSScriptRoot "..\.."),
  [switch]$Prerelease
)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$py = Join-Path $RepoPath ".venv\Scripts\python.exe"
$buildScript = Join-Path $RepoPath "tools\build_portable.py"
$releaseScript = Join-Path $RepoPath "tools\release.py"
$tag = "v$Version"
$zipName = "Tapesmith-portable-$Version.zip"
$zip = Join-Path $RepoPath "dist\$zipName"
$channel = if ($Prerelease) { "beta" } else { "stable" }
$outDir = Join-Path ([System.IO.Path]::GetTempPath()) "tapesmith-release-$Version"

foreach ($path in @($py, $buildScript, $releaseScript)) {
  if (-not (Test-Path $path)) { Write-Error "Fehlt: $path"; exit 1 }
}
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) { Write-Error "GitHub CLI gh fehlt"; exit 1 }
if (-not $Repo) {
  # Ohne -Repo: das GitHub-Repository des lokalen Checkouts (Remote origin).
  Push-Location $RepoPath
  try { $Repo = (& gh repo view --json nameWithOwner -q .nameWithOwner) } finally { Pop-Location }
  if (-not $Repo) { Write-Error "Repository nicht ermittelbar: -Repo owner/name angeben"; exit 1 }
}

# Idempotenz: vorhandenes Release nie ueberschreiben
# PowerShell 5.1 macht aus umgeleitetem stderr ("release not found") einen Fehler, der mit
# ErrorActionPreference Stop abbricht; hier zaehlt nur der Exit-Code.
$savedPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& gh release view $tag --repo $Repo *> $null
$viewExit = $LASTEXITCODE
$ErrorActionPreference = $savedPreference
if ($viewExit -eq 0) {
  Write-Host "Release $tag existiert bereits in $Repo. Abbruch; fuer eine neue Version -Version erhoehen."
  exit 1
}

$ghArgs = @("release", "create", $tag,
  (Join-Path $outDir "manifest.json"), (Join-Path $outDir "manifest.json.sig"), (Join-Path $outDir $zipName),
  "--repo", $Repo, "--title", "Tapesmith $Version", "--notes", $Notes)
if ($Prerelease) { $ghArgs += "--prerelease" }

if (-not $PSCmdlet.ShouldProcess("$Repo $tag", "bauen, signieren und veroeffentlichen")) {
  Write-Host "Wuerde ausfuehren:"
  Write-Host "  $py $buildScript --zip"
  Write-Host "  $py $releaseScript publish-dir --zip $zip --version $Version --channel $channel --notes ... --key $KeyPath --out $outDir"
  Write-Host "  gh $($ghArgs -join ' ')"
  exit 0
}

if (-not (Test-Path $KeyPath)) { Write-Error "Signaturschluessel fehlt: $KeyPath (tools\release.py keygen)"; exit 1 }

& $py $buildScript --zip
if ($LASTEXITCODE -ne 0) { Write-Error "Build fehlgeschlagen"; exit 1 }
if (-not (Test-Path $zip)) { Write-Error "Zip fehlt: $zip (passt -Version zu src\tapesmith\__init__.py?)"; exit 1 }

if (Test-Path $outDir) { Remove-Item -Recurse -Force $outDir }
& $py $releaseScript publish-dir --zip $zip --version $Version --channel $channel --notes $Notes --key $KeyPath --out $outDir
if ($LASTEXITCODE -ne 0) { Write-Error "Signieren fehlgeschlagen"; exit 1 }

& gh @ghArgs
if ($LASTEXITCODE -ne 0) { Write-Error "gh release create fehlgeschlagen"; exit 1 }
Write-Host "Veroeffentlicht: $Repo $tag ($channel)"
exit 0
