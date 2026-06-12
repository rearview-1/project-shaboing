@echo off
setlocal EnableExtensions
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
  set "PY=.venv\Scripts\python.exe"
) else (
  set "PY=python"
)

echo Updating static game data from public sources...
"%PY%" -m tools.extract_game_data --backup
if errorlevel 1 (
  echo ERROR: Game data extraction failed.
  pause
  exit /b 1
)

echo.
echo Verifying generated game data...
"%PY%" -m tools.verify_game_data
if errorlevel 1 (
  echo ERROR: Game data verification failed.
  pause
  exit /b 1
)

echo.
echo Game data update complete.
pause
