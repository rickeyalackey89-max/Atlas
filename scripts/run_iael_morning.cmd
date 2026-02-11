@echo off
setlocal

set ATLAS_ROOT=C:\Users\rick\projects\Atlas
set DASH_ROOT=C:\Users\rick\projects\AtlasDashboard
set LOG=%ATLAS_ROOT%\data\output\telemetry\iael_runs.log

cd /d %ATLAS_ROOT%
echo.>> %LOG%
echo ===== %date% %time% IAEL RUN START =====>> %LOG%

REM (1) Injury context (optional)
python scripts\injury\injury_pull_and_parse.py >> %LOG% 2>&1
if errorlevel 1 (
  echo [FAIL] injury_pull_and_parse >> %LOG%
  exit /b 1
)

REM (2) Generate latest outputs (THIS is the missing piece)
python run_today.py >> %LOG% 2>&1
if errorlevel 1 (
  echo [FAIL] run_today.py >> %LOG%
  exit /b 1
)

REM (3) Export to dashboard + commit + push (THIS is what makes mobile work)
cd /d %DASH_ROOT%
powershell -NoProfile -ExecutionPolicy Bypass -File publish-atlas.ps1 "%ATLAS_ROOT%" >> %LOG% 2>&1
if errorlevel 1 (
  echo [FAIL] publish-atlas.ps1 >> %LOG%
  exit /b 1
)

REM (4) Notify
cd /d %ATLAS_ROOT%
python scripts\alerts\slack_notify.py >> %LOG% 2>&1

echo ===== %date% %time% IAEL RUN END =====>> %LOG%
exit /b 0