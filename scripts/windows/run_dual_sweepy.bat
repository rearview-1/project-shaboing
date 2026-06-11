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
"%PY%" tools\verify_project_integrity.py
if errorlevel 1 (
  pause
  exit /b 1
)
"%PY%" tools\launch_dual_sweepy.py
pause
