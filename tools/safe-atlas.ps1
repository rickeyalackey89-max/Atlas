# ===============================
# Atlas Safe Mode Runner
# ===============================

[CmdletBinding()]
param(
    # Max runtime in minutes before hard kill
    [int]$TimeoutMinutes = 20,

    # Atlas arguments (default = safest path)
    [string[]]$AtlasArgs = @("publish", "-OnlyExport")
)

$ErrorActionPreference = "Stop"

Write-Host "🛡️ Atlas SAFE MODE starting..." -ForegroundColor Cyan

# -------------------------------
# 1. Hard CPU / BLAS thread caps
# -------------------------------
$env:OMP_NUM_THREADS      = "1"
$env:MKL_NUM_THREADS      = "1"
$env:OPENBLAS_NUM_THREADS = "1"
$env:NUMEXPR_NUM_THREADS  = "1"

Write-Host "✔️ CPU thread caps applied"

# -------------------------------
# 2. Logging
# -------------------------------
$logDir = Join-Path $PSScriptRoot "..\logs"
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir | Out-Null
}

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logFile = Join-Path $logDir "atlas_safe_$timestamp.log"

Start-Transcript -Path $logFile
Write-Host "📄 Transcript started: $logFile"

# -------------------------------
# 3. Launch Atlas as child process
# -------------------------------
$atlasPath = Join-Path $PSScriptRoot "..\atlas.ps1"

if (-not (Test-Path $atlasPath)) {
    throw "atlas.ps1 not found at expected path: $atlasPath"
}

$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = "powershell.exe"
$psi.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$atlasPath`" $($AtlasArgs -join ' ')"
$psi.UseShellExecute = $false
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError  = $true
$psi.CreateNoWindow = $true

$process = New-Object System.Diagnostics.Process
$process.StartInfo = $psi

Write-Host "🚀 Launching Atlas with args: $($AtlasArgs -join ' ')"

$null = $process.Start()

# Stream output live into transcript
$stdOut = $process.StandardOutput
$stdErr = $process.StandardError

$timeout = [TimeSpan]::FromMinutes($TimeoutMinutes)
$sw = [System.Diagnostics.Stopwatch]::StartNew()

while (-not $process.HasExited) {
    while (-not $stdOut.EndOfStream) {
        Write-Host $stdOut.ReadLine()
    }
    while (-not $stdErr.EndOfStream) {
        Write-Warning $stdErr.ReadLine()
    }

    if ($sw.Elapsed -gt $timeout) {
        Write-Error "⏱️ TIMEOUT exceeded ($TimeoutMinutes minutes). Killing Atlas process."
        $process.Kill()
        throw "Atlas terminated due to timeout."
    }

    Start-Sleep -Milliseconds 200
}

$sw.Stop()

# Drain remaining output
while (-not $stdOut.EndOfStream) {
    Write-Host $stdOut.ReadLine()
}
while (-not $stdErr.EndOfStream) {
    Write-Warning $stdErr.ReadLine()
}

if ($process.ExitCode -ne 0) {
    throw "Atlas exited with code $($process.ExitCode)"
}

Write-Host "✅ Atlas SAFE MODE completed successfully in $($sw.Elapsed.TotalMinutes.ToString('0.00')) minutes"

Stop-Transcript