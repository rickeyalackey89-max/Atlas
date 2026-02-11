# Extracted into module Private/
# Source: run_today_and_export.ps1:37-50
function Assert-FreshFile {
    param(
        [Parameter(Mandatory=$true)][string]$Path,
        [Parameter(Mandatory=$true)][string]$Label,
        [int]$MaxAgeMinutes = 240
    )
    if (-not (Test-Path $Path)) { throw "Freshness guard FAILED: missing $Label at $Path" }
    $fi = Get-Item $Path
    $ageMin = [int](((Get-Date) - $fi.LastWriteTime).TotalMinutes)
    if ($ageMin -gt $MaxAgeMinutes) {
        throw "Freshness guard FAILED: $Label is stale ($ageMin min old): $Path (LastWriteTime=$($fi.LastWriteTime))"
    }
    Write-Host ("[OK] {0} fresh ({1} min old) -> {2}" -f $Label, $ageMin, $Path)
}

