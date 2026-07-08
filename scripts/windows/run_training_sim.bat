@echo off
cd /d "%~dp0..\.."

set "PY=python"
if exist ".venv\Scripts\python.exe" (
  set "PY=.venv\Scripts\python.exe"
) else (
  where python >nul 2>nul
  if errorlevel 1 (
    echo Python is not on your PATH and .venv was not found.
    echo Run setup_and_run_sweepy.bat first, or install Python 3.10+ from https://www.python.org/downloads/.
    pause
    exit /b 1
  )
)

if not defined SWEEPY_TRAINING_SIM_PORT set "SWEEPY_TRAINING_SIM_PORT=1818"
if not defined SWEEPY_TRAINING_SIM_HOST set "SWEEPY_TRAINING_SIM_HOST=127.0.0.1"

"%PY%" tools\verify_project_integrity.py --compile
if errorlevel 1 (
  pause
  exit /b 1
)

echo.
echo ================================================================
echo  Sweepy Training Sim
echo ================================================================
echo  No login/auth is required.
echo  URL: http://%SWEEPY_TRAINING_SIM_HOST%:%SWEEPY_TRAINING_SIM_PORT%
echo ================================================================
echo.

"%PY%" training_sim_server.py
pause
