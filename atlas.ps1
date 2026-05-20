# Atlas MLB Dev wrapper.

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$run = Join-Path $PSScriptRoot 'AtlasMLB.ps1'
if (-not (Test-Path -LiteralPath $run)) {
    throw "Missing MLB-dev runner: $run"
}

Write-Host "atlas.ps1 -> forwarding to Atlas MLB Dev runner: .\AtlasMLB.ps1"

& pwsh -NoProfile -ExecutionPolicy Bypass -File $run @args
exit $LASTEXITCODE
