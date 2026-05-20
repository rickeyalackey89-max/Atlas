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
# - Use this repo's local Python environment when present.

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

$srcPath = Join-Path $here "src"
if ($env:PYTHONPATH) {
    $env:PYTHONPATH = "$srcPath;$env:PYTHONPATH"
} else {
    $env:PYTHONPATH = $srcPath
}

$venvCandidates = @(
    (Join-Path $here ".venv\Scripts\python.exe"),
    (Join-Path $here ".venv314\Scripts\python.exe")
)
$python = $venvCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $python) {
    $python = "py"
}

# MLB-dev invocation. This intentionally does not call Atlas.cli.
& $python -m mlb.cli $mode @rest

exit $LASTEXITCODE
