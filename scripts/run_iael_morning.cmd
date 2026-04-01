@echo off
setlocal

REM ================================================================
REM run_iael_morning.cmd — Early data pre-fetch (no model run)
REM Schedule: ~9:00 AM ET  (before first live run)
REM
REM Refreshes external data sources so the 11 AM live run starts
REM with warm caches: gamelogs, defense stats, role metrics,
REM crafted player stats, rotowire lines.
REM ================================================================

set ATLAS_ROOT=C:\Users\rick\projects\Atlas
set PY=%ATLAS_ROOT%\.venv\Scripts\python.exe
set LOG=%ATLAS_ROOT%\data\telemetry\iael_runs.log

cd /d %ATLAS_ROOT%
echo.>> %LOG%
echo ===== %date% %time% MORNING PRE-FETCH START =====>> %LOG%

%PY% tools\refresh_nba_gamelogs.py >> %LOG% 2>&1
if errorlevel 1 (
  echo [WARN] refresh_nba_gamelogs failed >> %LOG%
)

%PY% tools\fetch_nba_defense_stats.py >> %LOG% 2>&1
if errorlevel 1 (
  echo [WARN] fetch_nba_defense_stats failed >> %LOG%
)

%PY% tools\fetch_role_metrics.py >> %LOG% 2>&1
if errorlevel 1 (
  echo [WARN] fetch_role_metrics failed >> %LOG%
)

%PY% tools\fetch_crafted_player_stats.py >> %LOG% 2>&1
if errorlevel 1 (
  echo [WARN] fetch_crafted_player_stats failed >> %LOG%
)

%PY% tools\fetch_rotowire_lines.py >> %LOG% 2>&1
if errorlevel 1 (
  echo [WARN] fetch_rotowire_lines failed >> %LOG%
)

echo ===== %date% %time% MORNING PRE-FETCH END =====>> %LOG%
exit /b 0