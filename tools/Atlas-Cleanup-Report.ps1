#requires -Version 5.1
[CmdletBinding()]
param(
  [string]$RepoRoot = (Get-Location).Path
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$root = (Resolve-Path -LiteralPath $RepoRoot).Path

$files = Get-ChildItem -LiteralPath $root -Recurse -File -Force |
  Where-Object { $_.FullName -notmatch '\\\.git\\' -and $_.FullName -notmatch '\\node_modules\\' }

$ps1 = $files | Where-Object Extension -eq '.ps1'
$py  = $files | Where-Object Extension -eq '.py'

# Heuristic buckets
$entryPs = $ps1 | Where-Object { $_.DirectoryName -eq $root }
$modulePs = $ps1 | Where-Object { $_.FullName -match '\\src\\Atlas\\' }
$toolsPy  = $py  | Where-Object { $_.FullName -match '\\tools\\' }
$scriptsPy= $py  | Where-Object { $_.FullName -match '\\scripts\\' }
$corePy   = $py  | Where-Object { $_.FullName -match '\\src\\' }

[pscustomobject]@{
  RepoRoot = $root
  TotalFiles = $files.Count
  PowerShellRootScripts = $entryPs.Count
  PowerShellModuleFiles = $modulePs.Count
  PythonCore = $corePy.Count
  PythonTools = $toolsPy.Count
  PythonScripts = $scriptsPy.Count
} | Format-List

Write-Host "`nRoot PowerShell scripts:" -ForegroundColor Cyan
$entryPs | Sort-Object Name | Select-Object Name, FullName | Format-Table -AutoSize

Write-Host "`nPotentially redundant (root PS scripts not atlas.ps1):" -ForegroundColor Yellow
$entryPs | Where-Object Name -ne 'atlas.ps1' | Sort-Object Name | Select-Object Name, FullName | Format-Table -AutoSize

Write-Host "`nModule exports:" -ForegroundColor Cyan
Import-Module (Join-Path $root 'src\Atlas') -Force
Get-Command -Module Atlas | Sort-Object Name | Format-Table Name,CommandType