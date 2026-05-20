Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Atlas MLB Dev runner:
#   .\AtlasMLB.ps1          -> python -m mlb.cli doctor
#   .\AtlasMLB.ps1 markets  -> python -m mlb.cli markets
#
# Purpose:
# - Keep Atlas-MLB-dev from accidentally invoking copied NBA live code.
# - Preserve a simple local Windows wrapper while MLB architecture is built.
# - Keep the canonical command surface in the atlas-mlb Python CLI.
# - Use this repo's local .venv314 interpreter.

Write-Host ""
Write-Host "============================================" -ForegroundColor DarkGray
Write-Host "             ATLAS MLB DEV                  " -ForegroundColor Yellow
Write-Host "============================================" -ForegroundColor DarkGray
Write-Host ""

# Pass-through args to the MLB dev CLI.
# Default mode is "doctor" if none provided.
if ($args.Count -eq 0) {
    $mode = "doctor"
    $rest = @()
} else {
    $mode = $args[0]
    if ($args.Count -gt 1) { $rest = $args[1..($args.Count-1)] } else { $rest = @() }
}

# Ensure we're running from the directory containing this script (repo root expectation)
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here
$python = Join-Path $here ".venv314\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Missing Atlas-MLB-dev Python environment: $python"
}

# MLB-dev invocation. This intentionally does not call Atlas.cli.
& $python -m mlb.cli $mode @rest

exit $LASTEXITCODE
