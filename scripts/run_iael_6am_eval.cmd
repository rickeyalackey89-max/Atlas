@echo off
setlocal enabledelayedexpansion

REM ================================================================
REM run_iael_6am_eval.cmd — Morning eval backfill
REM Schedule: ~6:00 AM ET (before morning pre-fetch)
REM
REM Pulls yesterday's NBA box scores into gamelogs, then writes
REM eval_legs.csv for every live run from the previous day.
REM This is the truth-backfill step that makes Brier scoring work.
REM ================================================================

set ATLAS_ROOT=C:\Users\13142\Atlas\Atlas
set PY=%ATLAS_ROOT%\.venv\Scripts\python.exe
if not exist "%PY%" set PY=%ATLAS_ROOT%\.venv314\Scripts\python.exe
set LOG=%ATLAS_ROOT%\data\telemetry\iael_runs.log
set GAMELOGS=%ATLAS_ROOT%\data\gamelogs\nba_gamelogs.csv

cd /d %ATLAS_ROOT%
echo.>> %LOG%
echo ===== %date% %time% 6AM EVAL BACKFILL START =====>> %LOG%
if not exist "%PY%" (
  echo [FAIL] Python executable not found. Checked .venv and .venv314 >> %LOG%
  exit /b 1
)
if not exist "%ATLAS_ROOT%\logs" mkdir "%ATLAS_ROOT%\logs"
echo [PY] %PY% >> %LOG%

REM (1) Refresh gamelogs (pulls yesterday's box scores from NBA API)
%PY% tools\refresh_nba_gamelogs.py >> %LOG% 2>&1
if errorlevel 1 (
  echo [FAIL] refresh_nba_gamelogs >> %LOG%
  exit /b 1
)
echo [OK] Gamelogs refreshed >> %LOG%

REM (2) Build eval legs for yesterday's live runs in data/telemetry/live_runs/
REM     Find yesterday's date tag (YYYYMMDD) and ISO date.
for /f "delims=" %%y in ('%PY% -c "from datetime import date,timedelta;print((date.today()-timedelta(days=1)).strftime('%%Y%%m%%d'))"') do set YESTERDAY=%%y
set YESTERDAY_ISO=%YESTERDAY:~0,4%-%YESTERDAY:~4,2%-%YESTERDAY:~6,2%
echo [EVAL] Looking for live runs from %YESTERDAY% >> %LOG%
%PY% tools\run_6am_eval_backfill.py --date %YESTERDAY_ISO% --atlas-root "%ATLAS_ROOT%" --gamelogs-path "%GAMELOGS%" >> %LOG% 2>&1
set EVAL_BACKFILL_RC=%ERRORLEVEL%
if "%EVAL_BACKFILL_RC%"=="0" (
  echo [OK] Eval backfill completed for %YESTERDAY_ISO% >> %LOG%
) else if "%EVAL_BACKFILL_RC%"=="2" (
  echo [WARN] Eval backfill found no eligible runs for %YESTERDAY_ISO% >> %LOG%
) else (
  echo [WARN] Eval backfill reported failures for %YESTERDAY_ISO% rc=%EVAL_BACKFILL_RC% >> %LOG%
)

REM (3) Select the canonical prior-day report run.
set REPORT_RUN=
for /f "delims=" %%r in ('%PY% tools\select_eval_report_run.py --date %YESTERDAY_ISO% --runs-dir "%ATLAS_ROOT%\data\output\runs" --require-eval') do set REPORT_RUN=%%r
if defined REPORT_RUN (
  echo [EVAL] Selected canonical report run !REPORT_RUN! >> %LOG%
) else (
  echo [WARN] No canonical report run with eval_legs.csv found for %YESTERDAY_ISO% >> %LOG%
)

REM (4) Daily slip-selection health diagnostic
set SLIP_DIAG_OUT=%ATLAS_ROOT%\logs\slip_failure_diag_%YESTERDAY%.json
echo [DIAG] Running slip selection diagnostic for %YESTERDAY_ISO% >> %LOG%
%PY% scripts\audits\slip_failure_diagnostic.py --dates %YESTERDAY_ISO% --json-out "%SLIP_DIAG_OUT%" >> %LOG% 2>&1
if errorlevel 1 (
  echo [WARN] Slip selection diagnostic failed (non-fatal) >> %LOG%
) else (
  echo [OK] Slip selection diagnostic written to %SLIP_DIAG_OUT% >> %LOG%
)

REM (5) Post yesterday's results to Discord #results channel
echo [DISCORD] Posting yesterday's slip results to Discord >> %LOG%
if not defined REPORT_RUN (
  echo [WARN] Discord results skipped because no canonical report run was selected >> %LOG%
  goto :after_discord
)
%PY% tools\discord_post.py --date %YESTERDAY_ISO% --run-dir "!REPORT_RUN!" >> %LOG% 2>&1
if errorlevel 1 (
  echo [WARN] Discord results post failed (non-fatal) >> %LOG%
) else (
  echo [OK] Discord results posted >> %LOG%
)
:after_discord

REM (6) Rebuild dashboard payload + publish (captures fresh yesterday_slips record)
set VENV_PY=%PY%
if not defined REPORT_RUN (
  echo [WARN] No canonical report run selected, skipping payload rebuild to avoid publishing stale/live-mixed slips >> %LOG%
  goto :end
)
set ATLAS_YESTERDAY_REPORT_RUN=!REPORT_RUN!
echo [PUBLISH] Rebuilding dashboard payload for !REPORT_RUN! using report run !REPORT_RUN! >> %LOG%
%VENV_PY% src\Atlas\stages\publish\build_cloudflare_payload.py "!REPORT_RUN!" >> %LOG% 2>&1
set PAYLOAD_RC=%ERRORLEVEL%
set ATLAS_YESTERDAY_REPORT_RUN=
if not "%PAYLOAD_RC%"=="0" (
  echo [WARN] Payload rebuild failed (non-fatal) >> %LOG%
  goto :end
)
echo [PUBLISH] Publishing to dashboard >> %LOG%
powershell.exe -ExecutionPolicy RemoteSigned -File "%ATLAS_ROOT%\..\atlas-dashboard\publish-atlas.ps1" -AtlasRoot "%ATLAS_ROOT%" >> %LOG% 2>&1
if errorlevel 1 (
  echo [WARN] Dashboard publish failed (non-fatal) >> %LOG%
) else (
  echo [OK] Dashboard published with fresh stats >> %LOG%
)

:end
echo ===== %date% %time% 6AM EVAL BACKFILL END =====>> %LOG%
exit /b 0
