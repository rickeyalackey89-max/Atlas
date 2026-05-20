Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Simple wrapper around the canonical operator entrypoint:
#   py -m NBA.cli live
#
# Purpose:
# - Keep ONE NBA model entrypoint for operators (NBA.cli)
# - Preserve Atlas.cli as a compatibility alias for older automation
# - Preserve the legacy banner / UX
# - Avoid ProcessStartInfo quirks (env vars + differing banners / paths)

Write-Host ""
Write-Host "============================================" -ForegroundColor DarkGray
Write-Host "           LETS MAKE SOME MONEY!            " -ForegroundColor Yellow
Write-Host "============================================" -ForegroundColor DarkGray
Write-Host ""

# Pass-through args:
#   .\run.ps1 live        -> py -m NBA.cli live
#   .\run.ps1 replay ...  -> py -m NBA.cli replay ...
#
# Default mode is "live" if none provided.
if ($args.Count -eq 0) {
    $mode = "live"
    $rest = @()
} else {
    $mode = $args[0]
    if ($args.Count -gt 1) { $rest = $args[1..($args.Count-1)] } else { $rest = @() }
}

# Ensure we're running from the directory containing this script (repo root expectation)
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here

# Keep the src-layout importable even after folder renames or machine restores.
$srcPath = Join-Path $here "src"
if ($env:PYTHONPATH) {
    $env:PYTHONPATH = "$srcPath;$env:PYTHONPATH"
} else {
    $env:PYTHONPATH = $srcPath
}

# Canonical invocation (operator-facing namespace)
& py -m NBA.cli $mode @rest

exit $LASTEXITCODE
