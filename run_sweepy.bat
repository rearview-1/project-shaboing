@echo off
cd /d "%~dp0"
set "SWEEPY_PROJECT_ROOT=%CD%"
set "SWEEPY_RESTART_SCRIPT=%CD%\main.py"
set "SWEEPY_SUPERVISED=1"
if not exist ".git" (
  echo [WARN] This folder is not a git clone, so Refresh Backend cannot auto-update from GitHub.
  echo        Reinstall with: git clone https://github.com/rearview-1/project-shaboing.git
  echo.
)
if not defined SWEEPY_AUTO_GIT_UPDATE set "SWEEPY_AUTO_GIT_UPDATE=1"
if not defined SWEEPY_AUTO_GIT_UPDATE_INITIAL_DELAY_SEC set "SWEEPY_AUTO_GIT_UPDATE_INITIAL_DELAY_SEC=0"
set "PY=python"
if exist ".venv\Scripts\python.exe" (
  set "PY=%CD%\.venv\Scripts\python.exe"
) else (
  where python >nul 2>nul
  if errorlevel 1 (
    echo Python is not on your PATH and .venv was not found.
    echo Run setup_and_run_sweepy.bat first, or install Python 3.10+ from https://www.python.org/downloads/.
    pause
    exit /b 1
  )
)
set "SWEEPY_RESTART_PYTHON=%PY%"
"%PY%" tools\verify_project_integrity.py
if errorlevel 1 (
  pause
  exit /b 1
)
:run
"%PY%" main.py
if "%errorlevel%"=="73" goto run
pause
