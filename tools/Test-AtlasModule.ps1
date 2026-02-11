#requires -Version 5.1
[CmdletBinding()]
param(
  [string]$RepoRoot = (Get-Location).Path,
  [string]$ModuleName = "Atlas"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$modulePath = Join-Path $RepoRoot ("src\" + $ModuleName)
Import-Module $modulePath -Force

Write-Host "✅ Imported $ModuleName from $modulePath" -ForegroundColor Green
Write-Host "Public commands:" -ForegroundColor Cyan
Get-Command -Module $ModuleName | Sort-Object Name | Format-Table Name, CommandType

# Optional: call Invoke-Atlas if it exists
if (Get-Command -Name "Invoke-Atlas" -ErrorAction SilentlyContinue) {
  Write-Host "`nRunning Invoke-Atlas -WhatIf (if supported)..." -ForegroundColor Yellow
  try {
    Invoke-Atlas -WhatIf
  } catch {
    Write-Warning "Invoke-Atlas call failed (might not support -WhatIf yet): $($_.Exception.Message)"
  }
}