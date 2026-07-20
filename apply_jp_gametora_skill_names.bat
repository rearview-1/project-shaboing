@echo off
setlocal

cd /d "%~dp0"

set "PYTHON_EXE=python"
if exist ".venv\Scripts\python.exe" set "PYTHON_EXE=.venv\Scripts\python.exe"

if /I not "%SWEEPY_SKIP_GAMETORA_FETCH%"=="1" (
  "%PYTHON_EXE%" "tools\extract_gametora_skill_overrides.py"
  if errorlevel 1 (
    echo.
    echo Warning: could not refresh GameTora skill data. Applying cached data if present.
  )
)

"%PYTHON_EXE%" "tools\apply_gametora_hachimi_skill_names.py" %*
if errorlevel 1 (
  echo.
  echo Failed to apply GameTora skill names/descriptions. If the JP game is installed under Program Files,
  echo try running this .bat as Administrator or pass --hachimi-dir "PATH_TO_HACHIMI".
  pause
  exit /b 1
)

echo.
echo JP Hachimi skill names are using GameTora names, with Hachimi mechanics descriptions preserved.
pause
