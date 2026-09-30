@echo off
rem Tapesmith aus dem Quellordner starten (Entwicklungsversion).
rem   tools\dev-start.cmd        beendet laufendes Tapesmith, startet das Tray aus .venv; baut die
rem                              Weboberflaeche vorher neu, wenn unter web\ etwas geaendert wurde
rem   tools\dev-build-start.cmd  baut die Weboberflaeche immer neu (web\ nach webui\static)
rem   tools\installed-start.cmd  beendet laufendes Tapesmith, startet die installierte Version
setlocal
set "REPO=%~dp0.."
set "PY=%REPO%\.venv\Scripts\python.exe"
set "PYW=%REPO%\.venv\Scripts\pythonw.exe"
set "INSTALLED=%LOCALAPPDATA%\Programs\Tapesmith\current\Scripts\pythonw.exe"

if not exist "%PY%" (
    echo Keine Entwicklungsumgebung gefunden: %PY%
    echo Einrichten: py -3.11 -m venv .venv und .venv\Scripts\pip install -c constraints-ci.txt -e .
    exit /b 1
)

echo Beende laufendes Tapesmith ...
"%PY%" -m tapesmith daemon stop >nul 2>&1
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*tapesmith.gui.tray*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
ping -n 3 127.0.0.1 >nul

if /i "%~1"=="installed" (
    if not exist "%INSTALLED%" (
        echo Keine installierte Version gefunden: %INSTALLED%
        exit /b 1
    )
    start "" "%INSTALLED%" -m tapesmith.gui.tray
    echo Installierte Version gestartet.
    goto :status
)

set "NEEDBUILD="
if /i "%~1"=="build" set "NEEDBUILD=1"
rem Automatisch bauen, wenn unter web\ etwas neuer ist als der letzte Build
if not defined NEEDBUILD (
    powershell -NoProfile -Command "$b = Get-Item '%REPO%\src\tapesmith\webui\static\index.html' -ErrorAction SilentlyContinue; if (-not $b) { exit 1 }; $n = Get-ChildItem '%REPO%\web' -Recurse -File -Exclude *.test.ts,*.test.tsx | Where-Object { $_.FullName -notmatch '\\(node_modules|dist|coverage)\\' -and $_.LastWriteTime -gt $b.LastWriteTime } | Select-Object -First 1; if ($n) { exit 1 } else { exit 0 }"
    if errorlevel 1 set "NEEDBUILD=1"
)
if defined NEEDBUILD (
    echo Baue die Weboberflaeche ...
    rem --skip-check: schneller Build ohne Tests (die laufen in der CI und mit npm run check)
    "%PY%" "%REPO%\tools\build_web.py" --skip-check || (echo Build fehlgeschlagen. & if not defined TAPESMITH_NO_PAUSE pause & exit /b 1)
) else (
    echo Weboberflaeche ist aktuell, kein Build noetig.
)

pushd "%REPO%"
start "" "%PYW%" -m tapesmith.gui.tray
popd
echo Entwicklungsversion gestartet.

:status
ping -n 9 127.0.0.1 >nul
powershell -NoProfile -Command "try { $h = Invoke-RestMethod http://127.0.0.1:8712/health -TimeoutSec 5; 'Druckdienst laeuft, Version ' + $h.version } catch { 'Druckdienst antwortet noch nicht, das Tray startet ihn gleich.' }"
if not defined TAPESMITH_NO_PAUSE pause
endlocal
