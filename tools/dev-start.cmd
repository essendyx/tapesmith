@echo off
rem Tapesmith aus dem Quellordner starten (Entwicklungsversion).
rem   tools\dev-start.cmd            beendet laufendes Tapesmith, startet das Tray aus .venv
rem   tools\dev-start.cmd installed  beendet laufendes Tapesmith, startet die installierte Version
rem   tools\dev-start.cmd build      baut vorher die Weboberflaeche neu (web\ nach webui\static)
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
timeout /t 2 /nobreak >nul

if /i "%~1"=="installed" (
    if not exist "%INSTALLED%" (
        echo Keine installierte Version gefunden: %INSTALLED%
        exit /b 1
    )
    start "" "%INSTALLED%" -m tapesmith.gui.tray
    echo Installierte Version gestartet.
    goto :status
)

if /i "%~1"=="build" (
    echo Baue die Weboberflaeche ...
    "%PY%" "%REPO%\tools\build_web.py" || exit /b 1
)

pushd "%REPO%"
start "" "%PYW%" -m tapesmith.gui.tray
popd
echo Entwicklungsversion gestartet.

:status
timeout /t 8 /nobreak >nul
powershell -NoProfile -Command "try { $h = Invoke-RestMethod http://127.0.0.1:8712/health -TimeoutSec 5; 'Druckdienst laeuft, Version ' + $h.version } catch { 'Druckdienst antwortet noch nicht, das Tray startet ihn gleich.' }"
endlocal
