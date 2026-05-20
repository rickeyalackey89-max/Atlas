@echo off
setlocal enabledelayedexpansion

REM ================================================================
REM run_iael_230pm.cmd — Afternoon live re-run
REM Schedule: ~2:30 PM ET
REM
REM Full Atlas live pipeline with updated injury/line data.
REM Same as 11am but captures afternoon line movements.
REM ================================================================

set ATLAS_ROOT=C:\Users\13142\Atlas\NBA
set DASH_ROOT=C:\Users\13142\Atlas\atlas-dashboard
set PY=%ATLAS_ROOT%\.venv\Scripts\python.exe
if not exist "%PY%" set PY=%ATLAS_ROOT%\.venv314\Scripts\python.exe
set LOG=%ATLAS_ROOT%\data\telemetry\iael_runs.log

REM BettingPros is the default market odds provider. OddsAPI is optional legacy overlay.
set ATLAS_MARKET_ODDS_PROVIDER=bettingpros
if /I not "%ATLAS_MARKET_ODDS_PROVIDER%"=="bettingpros" (
  for /f "delims=" %%A in ('powershell -NoProfile -Command "[System.Environment]::GetEnvironmentVariable(\"ODDSAPI_KEY\",\"User\")"') do set ODDSAPI_KEY=%%A
  if not defined ODDSAPI_KEY (
    echo [WARN] ODDSAPI_KEY not set; optional OddsAPI overlay will be skipped >> %LOG%
  )
)

REM Load Discord webhooks from user registry if not already in the process environment.
REM Required for Task Scheduler processes that may not inherit the interactive session env.
if not defined DISCORD_PICKS_WEBHOOK_URL (
  for /f "delims=" %%A in ('powershell -NoProfile -Command "[System.Environment]::GetEnvironmentVariable(\"DISCORD_PICKS_WEBHOOK_URL\",\"User\")"') do set DISCORD_PICKS_WEBHOOK_URL=%%A
)
if not defined ATLAS_DISCORD_WEBHOOK (
  for /f "delims=" %%A in ('powershell -NoProfile -Command "[System.Environment]::GetEnvironmentVariable(\"ATLAS_DISCORD_WEBHOOK\",\"User\")"') do set ATLAS_DISCORD_WEBHOOK=%%A
)

REM 2:30PM updates the website, but does not post premium picks to Discord yet.
REM Weekend free-slip automation is tracked in ai/WEBSITE_TODO.md.
set ATLAS_DISCORD_PICKS_POST=0

cd /d %ATLAS_ROOT%
echo.>> %LOG%
echo ===== %date% %time% 230PM LIVE RUN START =====>> %LOG%

REM (1) Full live pipeline (IAEL preflight + fetch + score + publish + bundle)
%PY% -m Atlas.cli live >> %LOG% 2>&1
if errorlevel 1 (
  echo [FAIL] Atlas.cli live >> %LOG%
  exit /b 1
)

%PY% -c "import json,pathlib,sys; from datetime import date; p=pathlib.Path(r'%ATLAS_ROOT%\data\board\no_slate_today.json'); data=json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}; sys.exit(0 if data.get('status')=='no_slate' and data.get('today')==date.today().isoformat() else 1)"
if "%ERRORLEVEL%"=="0" (
  echo [LIVE] No NBA slate today; skipping dashboard publish and telemetry archive >> %LOG%
  goto :end
)

REM (2) Dashboard publish
cd /d %DASH_ROOT%
powershell -NoProfile -ExecutionPolicy Bypass -File publish-atlas.ps1 "%ATLAS_ROOT%" >> %LOG% 2>&1
if errorlevel 1 (
  echo [WARN] publish-atlas.ps1 failed >> %LOG%
)

REM (3) Archive run artifacts to telemetry
cd /d %ATLAS_ROOT%
set TODAY_TAG=%date:~10,4%%date:~4,2%%date:~7,2%
set TELEM_LIVE=%ATLAS_ROOT%\data\telemetry\live_runs\%TODAY_TAG%_230pm
if not exist "%TELEM_LIVE%" mkdir "%TELEM_LIVE%"

REM Find the latest run directory
for /f "delims=" %%d in ('dir /b /ad /od "%ATLAS_ROOT%\data\output\runs"') do set LATEST_RUN=%%d
if defined LATEST_RUN (
  set RUN_DIR=%ATLAS_ROOT%\data\output\runs\!LATEST_RUN!
  if exist "!RUN_DIR!\scored_legs_deduped.csv" copy "!RUN_DIR!\scored_legs_deduped.csv" "%TELEM_LIVE%\" >> %LOG% 2>&1
  if exist "!RUN_DIR!\scored_board.csv" copy "!RUN_DIR!\scored_board.csv" "%TELEM_LIVE%\" >> %LOG% 2>&1
  if exist "!RUN_DIR!\meta.json" copy "!RUN_DIR!\meta.json" "%TELEM_LIVE%\" >> %LOG% 2>&1
  if exist "!RUN_DIR!\slip_results.csv" copy "!RUN_DIR!\slip_results.csv" "%TELEM_LIVE%\" >> %LOG% 2>&1
  echo [TELEM] Archived run !LATEST_RUN! to %TELEM_LIVE% >> %LOG%
)

REM Copy latest bundle zip from data/bundles/ into both telemetry locations
for /f "delims=" %%b in ('dir /b /od "%ATLAS_ROOT%\data\bundles\atlas_bundle_*.zip" 2^>nul') do set LATEST_BUNDLE=%%b
if defined LATEST_BUNDLE (
  copy "%ATLAS_ROOT%\data\bundles\!LATEST_BUNDLE!" "%TELEM_LIVE%\" >> %LOG% 2>&1
  if not exist "%ATLAS_ROOT%\data\telemetry\bundles" mkdir "%ATLAS_ROOT%\data\telemetry\bundles"
  copy "%ATLAS_ROOT%\data\bundles\!LATEST_BUNDLE!" "%ATLAS_ROOT%\data\telemetry\bundles\" >> %LOG% 2>&1
  echo [TELEM] Bundle !LATEST_BUNDLE! archived >> %LOG%
)

:end
echo ===== %date% %time% 230PM LIVE RUN END =====>> %LOG%
exit /b 0

