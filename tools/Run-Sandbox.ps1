# ========================================================================
# ATLAS — SANDBOX ENTRYPOINT (Scenario replay)
# Runs replay_scenario.py which isolates outputs to data/output/sandbox_runs/
# ========================================================================

param(
    [Parameter(Mandatory = $true)]
    [string]$RawPath,

    [Parameter(Mandatory = $false)]
    [string]$Scenario = "manual"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not (Test-Path $RawPath)) {
    throw "Raw snapshot not found at path: $RawPath"
}

$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
$runId     = Get-Date -Format "yyyyMMdd_HHmmss"

$auditDir  = ".\.atlas_audit"
$runLog    = Join-Path $auditDir ("sandbox_runlog_{0}.txt" -f $runId)
$cmdLog    = Join-Path $auditDir ("sandbox_cmds_{0}.log" -f $runId)

New-Item -ItemType Directory -Force -Path $auditDir | Out-Null

Write-Host ""
Write-Host "╔══════════════════════════════════════════════════════════════════════════════╗"
Write-Host "║                                                                              ║"
Write-Host "║   ATLAS SANDBOX — SCENARIO SANDBOX (ISOLATED OUTPUTS)                        ║"
Write-Host "║                                                                              ║"
Write-Host "╚══════════════════════════════════════════════════════════════════════════════╝"
Write-Host ""
Write-Host ("🧾 Sandbox transcript: {0}" -f $runLog)
Write-Host ("🧾 CMD log:            {0}" -f $cmdLog)
Write-Host "================================================================"
Write-Host ("[SANDBOX] {0}" -f $timestamp)
Write-Host ("Scenario:    {0}" -f $Scenario)
Write-Host ("Raw Snapshot:{0}" -f $RawPath)
Write-Host "================================================================"
Write-Host ""

$pythonExe = "C:\Users\rick\AppData\Local\Programs\Python\Python311\python.exe"
if (-not (Test-Path $pythonExe)) {
    throw "Python executable not found at $pythonExe"
}

# repo-relative: tools/replay_scenario.py lives at repo root in your workspace
$scriptPath = ".\tools\replay_scenario.py"
if (-not (Test-Path $scriptPath)) {
    # fallback if script is at repo root (some copies were placed there during audits)
    $scriptPath = ".\replay_scenario.py"
}
if (-not (Test-Path $scriptPath)) {
    throw "replay_scenario.py not found at .\tools\replay_scenario.py or .\replay_scenario.py"
}

$cmd = @(
    $pythonExe,
    $scriptPath,
    $RawPath,
    "--scenario-id", $Scenario
)

("[{0}] {1}" -f $timestamp, ($cmd -join " ")) | Out-File -FilePath $cmdLog -Append -Encoding utf8
& $pythonExe $scriptPath $RawPath --scenario-id $Scenario 2>&1 | Tee-Object -FilePath $runLog

$exitCode = $LASTEXITCODE
if ($exitCode -ne 0) {
  Write-Host ""
  Write-Host "[ATLAS SANDBOX STOP] Scenario replay halted. ExitCode=$exitCode"
  exit $exitCode
}

Write-Host ""
Write-Host "[ATLAS SANDBOX COMPLETE] Scenario replay finished cleanly."
Write-Host ""