@echo off
cd /d "%~dp0"
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
python -m unittest discover -s tests -p "test_*_smoke.py"
pause
