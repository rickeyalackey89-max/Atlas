@echo off
setlocal enabledelayedexpansion

REM ================================================================
REM run_freebie_430pm.cmd — Discord freebie post
REM Schedule: ~4:30 PM ET
REM
REM Posts the daily freebie from the current NBA production output.
REM ================================================================

set ATLAS_ROOT=C:\Users\13142\Atlas\NBA
set PY=%ATLAS_ROOT%\.venv\Scripts\python.exe
if not exist "%PY%" set PY=%ATLAS_ROOT%\.venv314\Scripts\python.exe
set LOG=%ATLAS_ROOT%\data\telemetry\iael_runs.log

cd /d %ATLAS_ROOT%
echo.>> %LOG%
echo ===== %date% %time% 4:30PM FREEBIE POST START =====>> %LOG%
if not exist "%PY%" (
  echo [FAIL] Python executable not found. Checked .venv and .venv314 >> %LOG%
  exit /b 1
)
echo [PY] %PY% >> %LOG%

%PY% tools\discord_freebie_post.py >> %LOG% 2>&1
if errorlevel 1 (
  echo [FAIL] discord_freebie_post.py >> %LOG%
  exit /b 1
)

echo [OK] Discord freebie posted >> %LOG%
echo ===== %date% %time% 4:30PM FREEBIE POST END =====>> %LOG%
exit /b 0
