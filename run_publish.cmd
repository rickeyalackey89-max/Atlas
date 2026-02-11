@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM ============================================================================
REM Atlas Production Entrypoint
REM - Runs Atlas model
REM - Publishes outputs to AtlasDashboard
REM - Triggers Cloudflare via git push
REM ============================================================================

REM --- Hard set working directory ---
cd /d C:\Users\rick\projects\Atlas

REM --- Logging ---
set "LOG_DIR=C:\Users\rick\projects\Atlas\data\output\telemetry"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
set "LOG=%LOG_DIR%\publish_runs.log"

echo.>>"%LOG%"
echo ============================================================>>"%LOG%"
echo [%date% %time%] START run_publish.cmd>>"%LOG%"
echo CWD: %cd%>>"%LOG%"

REM ============================================================================
REM STEP 1: Run Atlas model
REM ============================================================================
echo [%date% %time%] RUN_MODEL_START>>"%LOG%"

REM Use Python Launcher (works even when python is not on PATH)
py -3 run_today.py >>"%LOG%" 2>&1
set "RC=!ERRORLEVEL!"

echo [%date% %time%] RUN_MODEL_DONE rc=!RC!>>"%LOG%"

if not "!RC!"=="0" (
    echo RUN_FAIL>>"%LOG%"
    echo PUBLISH_FAIL>>"%LOG%"
    exit /b !RC!
)

REM ============================================================================
REM STEP 2: Publish to AtlasDashboard (JSON export + git push)
REM ============================================================================
cd /d C:\Users\rick\projects\AtlasDashboard
echo [%date% %time%] PUBLISH_START>>"%LOG%"
echo CWD: %cd%>>"%LOG%"

powershell -NoProfile -ExecutionPolicy Bypass ^
  -File "C:\Users\rick\projects\AtlasDashboard\publish-atlas.ps1" ^
  "C:\Users\rick\projects\Atlas" >>"%LOG%" 2>&1

set "RC=!ERRORLEVEL!"
echo [%date% %time%] PUBLISH_DONE rc=!RC!>>"%LOG%"

if "!RC!"=="0" (
    echo PUBLISH_OK>>"%LOG%"
    exit /b 0
) else (
    echo PUBLISH_FAIL>>"%LOG%"
    exit /b !RC!
)