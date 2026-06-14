@echo off
REM ============================================================
REM  Sweepy packet sniffer -- OPT-IN, fully isolated launcher.
REM
REM  This is SEPARATE from the normal bot. It does NOT run main.py
REM  and does NOT change any system/proxy settings. It only LISTENS
REM  on a port; nothing routes through it unless YOU point your game
REM  client's proxy at 127.0.0.1:<port>. run_sweepy.bat /
REM  setup_and_run_sweepy.bat never reference this -- normal bot
REM  operation is completely unaffected.
REM
REM  Usage:   run_sniffer.bat            (port 8877, same as before)
REM           run_sniffer.bat 8899       (custom port)
REM ============================================================
setlocal EnableExtensions
cd /d "%~dp0"

if not defined SWEEPY_SNIFFER_PORT set "SWEEPY_SNIFFER_PORT=8877"
if not "%~1"=="" set "SWEEPY_SNIFFER_PORT=%~1"

set "PY=python"
if exist ".venv\Scripts\python.exe" (
  set "PY=%CD%\.venv\Scripts\python.exe"
) else (
  where python >nul 2>nul
  if errorlevel 1 (
    echo Python not found. Run setup_and_run_sweepy.bat first.
    pause
    exit /b 1
  )
)

REM Install the optional sniffer dependency (mitmproxy) only if missing.
"%PY%" -c "import mitmproxy" 1>nul 2>nul
if errorlevel 1 (
  echo Installing sniffer dependency ^(mitmproxy^)...
  "%PY%" -m pip install -r requirements-sniffer.txt
  if errorlevel 1 (
    echo ERROR: failed to install mitmproxy. See requirements-sniffer.txt
    pause
    exit /b 1
  )
)

echo.
echo ============================================================
echo  Sweepy packet sniffer  --  listening on 127.0.0.1:%SWEEPY_SNIFFER_PORT%
echo ------------------------------------------------------------
echo  1. Stop the old project's sniffer first (one interceptor per client).
echo  2. Point your game client's proxy at 127.0.0.1:%SWEEPY_SNIFFER_PORT%.
echo  3. Start the difficulty career in-game.
echo  Captures -^> uma_runtime\packet_captures\
echo            single_mode_free_start_latest.json = the Fuji answer
echo  Press Ctrl+C to stop.
echo ============================================================
echo.
"%PY%" -m uma_api.packet_sniffer
pause
