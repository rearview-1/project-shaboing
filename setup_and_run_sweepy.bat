@echo off
setlocal EnableExtensions
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

echo.
echo Sweepy fresh setup + launcher
echo =============================
echo This installs dependencies into .venv, creates local runtime folders,
echo verifies the project, then starts the backend.
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo ERROR: Python 3.10+ is not on PATH.
  echo Install Python from https://www.python.org/downloads/ and check "Add Python to PATH".
  pause
  exit /b 1
)

where node >nul 2>nul
if errorlevel 1 (
  echo ERROR: Node.js 18+ is not on PATH.
  echo Install it with: winget install -e --id OpenJS.NodeJS
  pause
  exit /b 1
)

where npm >nul 2>nul
if errorlevel 1 (
  echo ERROR: npm is not on PATH. Reinstall Node.js 18+.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating Python virtual environment...
  python -m venv .venv
  if errorlevel 1 (
    echo ERROR: Failed to create .venv.
    pause
    exit /b 1
  )
)

set "PY=%CD%\.venv\Scripts\python.exe"
set "SWEEPY_RESTART_PYTHON=%PY%"

echo Upgrading pip...
"%PY%" -m pip install --upgrade pip
if errorlevel 1 (
  echo ERROR: pip upgrade failed.
  pause
  exit /b 1
)

echo Installing Python dependencies...
"%PY%" -m pip install -r requirements.txt
if errorlevel 1 (
  echo ERROR: Python dependency install failed.
  pause
  exit /b 1
)

echo Installing optional packet-sniffer dependency ^(mitmproxy, for run_sniffer.bat^)...
"%PY%" -m pip install -r requirements-sniffer.txt
if errorlevel 1 (
  echo WARN: sniffer dependency install failed - this is OPTIONAL and does not
  echo       affect normal operation. run_sniffer.bat will retry it on demand.
)

echo Installing Node dependencies...
npm install
if errorlevel 1 (
  echo ERROR: npm install failed.
  pause
  exit /b 1
)

echo Creating runtime directories...
if not exist "uma_runtime" mkdir "uma_runtime"
if not exist "uma_runtime\instances" mkdir "uma_runtime\instances"
if not exist "uma_runtime\policy_models" mkdir "uma_runtime\policy_models"
if not exist "data\presets\saved" mkdir "data\presets\saved"
if not exist "data\presets\learned" mkdir "data\presets\learned"
if not exist "data\presets\starter" mkdir "data\presets\starter"
if not exist "data\presets\backups" mkdir "data\presets\backups"

echo Verifying project files...
set PYTHONDONTWRITEBYTECODE=1
"%PY%" tools\verify_project_integrity.py --compile
if errorlevel 1 (
  echo ERROR: Project integrity check failed. Fix the reported files before running.
  pause
  exit /b 1
)

echo.
echo Setup complete. Starting Sweepy...
echo Open the game client and authenticate if the UI asks for it.
echo.
:run
"%PY%" main.py
if "%errorlevel%"=="73" goto run
pause
