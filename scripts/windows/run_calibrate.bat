@echo off
REM Fast deck calibration - runs a strict optimizer sweep against your
REM currently plugged-in deck/trainee/scenario and saves the winning
REM strategy override to the deck policy cache. The bot picks it up
REM automatically on the next RUN CAREER (no restart needed).
REM
REM What this does, step-by-step:
REM   1. Reads dev_session.json to detect the deck you have set right now
REM   2. Runs a short baseline to see where the deck currently lands
REM   3. If baseline already hits SS comfortably, saves it as-is and exits
REM   4. Otherwise: adaptive candidate sweep within a ~4-minute time budget
REM      (total run, including final validation, stays at/under ~5 minutes)
REM   5. Early-stops the second a candidate hits the comfort threshold
REM   6. Validates the winner on fresh seeds
REM   7. Saves the winner to uma_runtime/instances/account_b/sim_calibration/deck_policies.json
REM
REM After this finishes, just click RUN CAREER in the UI as normal.
REM
REM Comfort gate (all five must hold):
REM   - SS rate     >= TARGET_SS_RATE       (default 0.95)
REM   - Mean rating >= TARGET_MEAN          (default 17500 = SS threshold)
REM   - Min rating  >= MIN_RATING           (default 14500 = no A+ batches)
REM   - Win rate    >= TARGET_WIN_RATE      (default 0.95)
REM   - Epithet-bonus losses <= MAX_EPITHET_LOSS  (default 2 - tolerates the
REM     2-sim screening noise; a career naturally drops 2-3 races by luck and
REM     ~7 G1s gate epithets, so demanding 0 rejected every candidate on noise
REM     even when it out-scored the baseline. The quality ranking still
REM     prefers FEWER epithet losses among savable candidates.)
REM
REM Optional env-var overrides:
REM   SWEEPY_CALIBRATE_TIME_BUDGET_SEC   default 240 (4 minutes; raise for a deeper search)
REM   SWEEPY_CALIBRATE_TARGET_SS_RATE    default 0.95
REM   SWEEPY_CALIBRATE_TARGET_MEAN       default 17500
REM   SWEEPY_CALIBRATE_TARGET_WIN_RATE   default 0.95
REM   SWEEPY_CALIBRATE_MAX_EPITHET_LOSS  default 2 (set 0 for strict no-epithet-loss)
REM   SWEEPY_CALIBRATE_MIN_RATING        default 14500

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

set TIME_BUDGET=240
set TARGET_SS_RATE=0.95
set TARGET_MEAN=17500
set TARGET_WIN_RATE=0.95
set MAX_EPITHET_LOSS=2
set MIN_RATING=14500

if not "%SWEEPY_CALIBRATE_TIME_BUDGET_SEC%"=="" set TIME_BUDGET=%SWEEPY_CALIBRATE_TIME_BUDGET_SEC%
if not "%SWEEPY_CALIBRATE_TARGET_SS_RATE%"=="" set TARGET_SS_RATE=%SWEEPY_CALIBRATE_TARGET_SS_RATE%
if not "%SWEEPY_CALIBRATE_TARGET_MEAN%"=="" set TARGET_MEAN=%SWEEPY_CALIBRATE_TARGET_MEAN%
if not "%SWEEPY_CALIBRATE_TARGET_WIN_RATE%"=="" set TARGET_WIN_RATE=%SWEEPY_CALIBRATE_TARGET_WIN_RATE%
if not "%SWEEPY_CALIBRATE_MAX_EPITHET_LOSS%"=="" set MAX_EPITHET_LOSS=%SWEEPY_CALIBRATE_MAX_EPITHET_LOSS%
if not "%SWEEPY_CALIBRATE_MIN_RATING%"=="" set MIN_RATING=%SWEEPY_CALIBRATE_MIN_RATING%

echo.
echo ================================================================
echo  CALIBRATE - Deck-specific strategy tuning
echo ================================================================
echo  Time budget:           %TIME_BUDGET% seconds
echo  Target SS rate:        %TARGET_SS_RATE%  (fraction of sims hitting SS)
echo  Target mean rating:    %TARGET_MEAN%  (SS threshold = 17500)
echo  Target win rate:       %TARGET_WIN_RATE%  (overall race win rate)
echo  Max epithet losses:    %MAX_EPITHET_LOSS%  (losses on Lady/Stunning/etc races)
echo  Min rating floor:      %MIN_RATING%  (14500 = no A+ calibration batches)
echo.
echo  Reading current deck from dev_session.json...
echo  Winner will be saved to deck_policies.json and picked up
echo  automatically on your next RUN CAREER.
echo ================================================================
echo.

"%PY%" tools\calibrate_deck.py ^
  --time-budget-sec %TIME_BUDGET% ^
  --validation-sims 3 ^
  --target-ss-rate %TARGET_SS_RATE% ^
  --target-mean %TARGET_MEAN% ^
  --target-win-rate %TARGET_WIN_RATE% ^
  --max-epithet-losses %MAX_EPITHET_LOSS% ^
  --min-rating %MIN_RATING%

echo.
echo ================================================================
echo  Calibration finished. Click RUN CAREER in the UI to use it.
echo ================================================================
pause
