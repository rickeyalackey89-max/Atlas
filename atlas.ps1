# atlas.ps1 (repo root) - LEGACY CLI wrapper
# Canonical production authority is: .\run.ps1
# This script only forwards to run.ps1 to prevent mixed execution paths.

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$run = Join-Path $PSScriptRoot 'run.ps1'
if (-not (Test-Path -LiteralPath $run)) {
    throw "Missing canonical runner: $run"
}

Write-Host "atlas.ps1 -> forwarding to canonical runner: .\run.ps1"

& pwsh -NoProfile -ExecutionPolicy Bypass -File $run
exit $LASTEXITCODE