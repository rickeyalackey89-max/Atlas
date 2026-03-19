Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Simple wrapper around the canonical entrypoint:
#   py -m Atlas.cli live
#
# Purpose:
# - Keep ONE model entrypoint (Atlas.cli)
# - Preserve the legacy banner / UX
# - Avoid ProcessStartInfo quirks (env vars + differing banners / paths)

Write-Host ""
Write-Host "============================================" -ForegroundColor DarkGray
Write-Host "           LETS MAKE SOME MONEY!            " -ForegroundColor Yellow
Write-Host "============================================" -ForegroundColor DarkGray
Write-Host ""

# Pass-through args:
#   .\run.ps1 live        -> py -m Atlas.cli live
#   .\run.ps1 replay ...  -> py -m Atlas.cli replay ...
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

# Canonical invocation (single source of truth)
& py -m Atlas.cli $mode @rest

exit $LASTEXITCODE
