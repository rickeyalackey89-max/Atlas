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
set PY=%ATLAS_ROOT%\.venv314\Scripts\python.exe
set LOG=%ATLAS_ROOT%\data\telemetry\iael_runs.log
set GAMELOGS=%ATLAS_ROOT%\data\gamelogs\nba_gamelogs.csv

cd /d %ATLAS_ROOT%
echo.>> %LOG%
echo ===== %date% %time% 6AM EVAL BACKFILL START =====>> %LOG%

REM (1) Refresh gamelogs (pulls yesterday's box scores from NBA API)
%PY% tools\refresh_nba_gamelogs.py >> %LOG% 2>&1
if errorlevel 1 (
  echo [FAIL] refresh_nba_gamelogs >> %LOG%
  exit /b 1
)
echo [OK] Gamelogs refreshed >> %LOG%

REM (2) Build eval legs for yesterday's live runs in data/telemetry/live_runs/
REM     Find yesterday's date tag (YYYYMMDD)
for /f "delims=" %%y in ('%PY% -c "from datetime import date,timedelta;print((date.today()-timedelta(days=1)).strftime('%%Y%%m%%d'))"') do set YESTERDAY=%%y
echo [EVAL] Looking for live runs from %YESTERDAY% >> %LOG%

set FOUND_RUNS=0
for /d %%r in ("%ATLAS_ROOT%\data\telemetry\live_runs\%YESTERDAY%_*") do (
  if exist "%%r\scored_legs_deduped.csv" (
    if exist "%%r\eval_legs.csv" (
      echo [EVAL] Skipping %%r (eval_legs.csv already exists) >> %LOG%
    ) else (
      echo [EVAL] Writing eval_legs for %%r >> %LOG%
      %PY% tools\create_eval_leg_backtestv2.py --run-dir "%%r" --gamelogs-path "%GAMELOGS%" >> %LOG% 2>&1
      if errorlevel 1 (
        echo [WARN] eval_legs failed for %%r >> %LOG%
      ) else (
        set /a FOUND_RUNS+=1
      )
    )
  )
)

REM (3) Also write eval legs for any runs still in data/output/runs/ from yesterday
for /d %%r in ("%ATLAS_ROOT%\data\output\runs\%YESTERDAY%_*") do (
  if exist "%%r\scored_legs_deduped.csv" (
    if exist "%%r\eval_legs.csv" (
      echo [EVAL] Skipping %%r (eval_legs.csv already exists) >> %LOG%
    ) else (
      echo [EVAL] Writing eval_legs for output run %%r >> %LOG%
      %PY% tools\create_eval_leg_backtestv2.py --run-dir "%%r" --gamelogs-path "%GAMELOGS%" >> %LOG% 2>&1
      if errorlevel 1 (
        echo [WARN] eval_legs failed for %%r >> %LOG%
      ) else (
        set /a FOUND_RUNS+=1
      )
    )
  )
)

echo [EVAL] Processed %FOUND_RUNS% run(s) with eval legs >> %LOG%

REM (4) Post yesterday's results to Discord #results channel
echo [DISCORD] Posting yesterday's slip results to Discord >> %LOG%
%PY% tools\discord_post.py --date %YESTERDAY:~0,4%-%YESTERDAY:~4,2%-%YESTERDAY:~6,2% >> %LOG% 2>&1
if errorlevel 1 (
  echo [WARN] Discord results post failed (non-fatal) >> %LOG%
) else (
  echo [OK] Discord results posted >> %LOG%
)

REM (5) Rebuild dashboard payload + publish (captures fresh yesterday_slips record)
set VENV_PY=%ATLAS_ROOT%\.venv314\Scripts\python.exe
for /f "delims=" %%r in ('%PY% -c "import os,sys; d=r\"%ATLAS_ROOT%\data\output\runs\"; runs=sorted([x for x in os.listdir(d) if len(x)==15 and x[8]==\"_\"], reverse=True); print(os.path.join(d,runs[0])) if runs else sys.exit(1)"') do set LATEST_RUN=%%r
if not defined LATEST_RUN (
  echo [WARN] No run dir found, skipping payload rebuild >> %LOG%
  goto :end
)
echo [PUBLISH] Rebuilding dashboard payload for %LATEST_RUN% >> %LOG%
%VENV_PY% src\Atlas\stages\publish\build_cloudflare_payload.py "%LATEST_RUN%" >> %LOG% 2>&1
if errorlevel 1 (
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
