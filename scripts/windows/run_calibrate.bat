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
REM   4. Otherwise: adaptive candidate sweep within a 30-minute time budget
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
REM   - Epithet-bonus losses <= MAX_EPITHET_LOSS  (default 0 - no losses on
REM     races that gate Lady/Stunning/Heroine/Goddess/etc bonuses)
REM
REM Optional env-var overrides:
REM   SWEEPY_CALIBRATE_TIME_BUDGET_SEC   default 1800 (30 minutes)
REM   SWEEPY_CALIBRATE_TARGET_SS_RATE    default 0.95
REM   SWEEPY_CALIBRATE_TARGET_MEAN       default 17500
REM   SWEEPY_CALIBRATE_TARGET_WIN_RATE   default 0.95
REM   SWEEPY_CALIBRATE_MAX_EPITHET_LOSS  default 0
REM   SWEEPY_CALIBRATE_MIN_RATING        default 14500

cd /d "%~dp0..\.."

where python >nul 2>nul
if errorlevel 1 (
  echo Python is not on your PATH. Install Python 3.10+ from https://www.python.org/downloads/ and re-run.
  pause
  exit /b 1
)
python tools\verify_project_integrity.py
if errorlevel 1 (
  pause
  exit /b 1
)

set TIME_BUDGET=1800
set TARGET_SS_RATE=0.95
set TARGET_MEAN=17500
set TARGET_WIN_RATE=0.95
set MAX_EPITHET_LOSS=0
set MIN_RATING=14500

if not "%SWEEPY_CALIBRATE_TIME_BUDGET_SEC%"=="" set TIME_BUDGET=%SWEEPY_CALIBRATE_TIME_BUDGET_SEC%
if not "%SWEEPY_CALIBRATE_TARGET_SS_RATE%"=="" set TARGET_SS_RATE=%SWEEPY_CALIBRATE_TARGET_SS_RATE%
if not "%SWEEPY_CALIBRATE_TARGET_MEAN%"=="" set TARGET_MEAN=%SWEEPY_CALIBRATE_TARGET_MEAN%
if not "%SWEEPY_CALIBRATE_TARGET_WIN_RATE%"=="" set TARGET_WIN_RATE=%SWEEPY_CALIBRATE_TARGET_WIN_RATE%
if not "%SWEEPY_CALIBRATE_MAX_EPITHET_LOSS%"=="" set MAX_EPITHET_LOSS=%SWEEPY_CALIBRATE_MAX_EPITHET_LOSS%
if not "%SWEEPY_CALIBRATE_MIN_RATING%"=="" set MIN_RATING=%SWEEPY_CALIBRATE_MIN_RATING%

echo.
echo ================================================================
echo  CALIBRATE — Deck-specific strategy tuning
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

python tools\calibrate_deck.py ^
  --time-budget-sec %TIME_BUDGET% ^
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
