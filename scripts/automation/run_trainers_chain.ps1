<#
.SYNOPSIS
    Watches for windfall trainer to finish, then auto-launches system trainer.
    Run this in its own terminal window and leave it overnight.
#>

$PYTHON   = "C:\Users\13142\Atlas\NBA\.venv\Scripts\python.exe"
if (-not (Test-Path $PYTHON)) {
    $PYTHON = "C:\Users\13142\Atlas\NBA\.venv314\Scripts\python.exe"
}
$TOOLS    = "C:\Users\13142\Atlas\NBA\tools"
$SENTINEL = "C:\Users\13142\Atlas\NBA\tools\leg_trainer_results_v5_windfall.yaml"
$SYSLOG   = "C:\Users\13142\Atlas\NBA\system_run1.log"

$env:PYTHONIOENCODING = 'utf-8'

Write-Host "=== Atlas Trainer Chain ===" -ForegroundColor Cyan
Write-Host "Watching for Windfall completion: $SENTINEL"
Write-Host "Will auto-launch System trainer when ready."
Write-Host "Started: $(Get-Date)"
Write-Host ""

# ── Wait for windfall results file ──────────────────────────────────────────
$pollSec = 300   # check every 5 minutes
$waited  = 0
while (-not (Test-Path $SENTINEL)) {
    $hrs = [int]($waited / 3600)
    $min = [int](($waited % 3600) / 60)
    Write-Host "  [$(Get-Date -Format 'HH:mm')]  Windfall still running... (waited ${hrs}h ${min}m)"
    Start-Sleep -Seconds $pollSec
    $waited += $pollSec
}

Write-Host ""
Write-Host "=== Windfall trainer FINISHED at $(Get-Date) ===" -ForegroundColor Green
Write-Host ""

# ── Print windfall summary from YAML ────────────────────────────────────────
Write-Host "--- Windfall results (first 40 lines) ---" -ForegroundColor Yellow
Get-Content $SENTINEL | Select-Object -First 40
Write-Host "..."
Write-Host ""

# ── Launch System trainer ────────────────────────────────────────────────────
Write-Host "=== Launching System trainer at $(Get-Date) ===" -ForegroundColor Cyan
& $PYTHON "$TOOLS\leg_trainer_v5_system.py" --workers 7 2>&1 | Tee-Object -FilePath $SYSLOG

Write-Host ""
Write-Host "=== System trainer FINISHED at $(Get-Date) ===" -ForegroundColor Green
Write-Host "Results: C:\Users\13142\Atlas\NBA\tools\leg_trainer_results_v5_system.yaml"
Write-Host "Log:     $SYSLOG"
