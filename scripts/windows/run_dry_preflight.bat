@echo off
cd /d "%~dp0..\.."
if "%~1"=="" (
  echo Usage: run_dry_preflight.bat tools\start_request.example.json
  pause
  exit /b 2
)
where python >nul 2>nul
if errorlevel 1 (
  echo Python is not on your PATH. Install Python 3.10+ from https://www.python.org/downloads/ and re-run.
  pause
  exit /b 1
)
set PYTHONDONTWRITEBYTECODE=1
python tools\verify_project_integrity.py
if errorlevel 1 (
  pause
  exit /b 1
)
python tools\dry_run_preflight.py --request "%~1"
pause
