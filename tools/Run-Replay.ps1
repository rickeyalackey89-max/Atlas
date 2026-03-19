# ========================================================================
# ATLAS — REPLAY ENTRYPOINT (telemetry-only; SAFE)
#
# This script intentionally does NOT call `python -m Atlas.cli replay`.
# It runs the telemetry/backtest reader over board snapshots and writes
# outputs ONLY under:
#   data\output\replay_runs\<STAMP>\...
#
# Modes:
#  - Default: last 7 calendar days ending today
#  - -Days N: last N calendar days ending today
#  - -Date YYYYMMDD: that single day
#  - -Snapshot board_YYYYMMDD_HHMMSS.csv (or full path): exact snapshot(s)
# ========================================================================

param(
  [int]$Days = 7,
  [string]$Date = "",
  [string[]]$Snapshot = @()
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Py = "C:\Users\rick\AppData\Local\Programs\Python\Python311\python.exe"
$Telemetry = Join-Path $RepoRoot "tools\telemetry_reader.py"
$OutDir = Join-Path $RepoRoot "data\output\replay_runs"

# Build args
$args = @($Telemetry, "--out-dir", $OutDir)

if ($Snapshot.Count -gt 0) {
  foreach ($s in $Snapshot) {
    $args += @("--snapshot", $s)
  }
}
elseif ($Date -ne "") {
  $args += @("--date", $Date)
}
else {
  $args += @("--days", "$Days")
}

Write-Host ("[Run-Replay] RepoRoot : " + $RepoRoot)
Write-Host ("[Run-Replay] OutDir   : " + $OutDir)
Write-Host ("[Run-Replay] Python   : " + $Py)
Write-Host ("[Run-Replay] Command  : " + ($args -join " "))

& $Py @args
