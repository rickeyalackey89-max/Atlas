# Extracted into module Private/
# Source: run_today_and_export.ps1:12-15
function Get-ProjectRoot {
    if ($MyInvocation.MyCommand.Path) { return (Split-Path -Parent $MyInvocation.MyCommand.Path) }
    return (Get-Location).Path
}

