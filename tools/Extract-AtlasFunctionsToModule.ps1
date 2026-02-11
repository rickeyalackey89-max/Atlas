#requires -Version 5.1
[CmdletBinding()]
param(
  [Parameter(Mandatory)]
  [ValidateScript({ Test-Path $_ -PathType Container })]
  [string]$RepoRoot,

  [string]$ModuleName = "Atlas",

  # Functions to extract (based on your function_index output)
  [string[]]$FunctionNames = @(
    "Get-ProjectRoot",
    "Resolve-Python",
    "Assert-FreshFile",
    "Assert-GamelogsFresh",
    "Banner"
  ),

  [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function New-Dir([string]$Path) {
  if (-not (Test-Path -LiteralPath $Path)) { New-Item -ItemType Directory -Path $Path | Out-Null }
}

$repo = (Resolve-Path -LiteralPath $RepoRoot).Path
$moduleRoot = Join-Path $repo "src\$ModuleName"
$privateDir = Join-Path $moduleRoot "Private"
New-Dir $privateDir

Add-Type -AssemblyName System.Management.Automation

# Scan only your main scripts (avoid tools/src)
$scanFiles = Get-ChildItem -LiteralPath $repo -File -Filter *.ps1 |
  Where-Object { $_.Name -in @("atlas.ps1","run_today_and_export.ps1","run_all_and_publish.ps1","live_feed_publish.ps1") }

if (-not $scanFiles) { throw "No target scripts found in repo root to scan." }

$found = @()

foreach ($f in $scanFiles) {
  $tokens = $null; $errors = $null
  $ast = [System.Management.Automation.Language.Parser]::ParseFile($f.FullName, [ref]$tokens, [ref]$errors)

  foreach ($e in @($errors)) {
    Write-Warning ("Parse error in {0}:{1} {2}" -f $f.Name, $e.Extent.StartLineNumber, $e.Message)
  }

  $funcAsts = $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $true)

  foreach ($fn in $funcAsts) {
    if ($FunctionNames -contains $fn.Name) {
      $dest = Join-Path $privateDir ($fn.Name + ".ps1")
      if ((Test-Path -LiteralPath $dest) -and (-not $Force)) {
        Write-Warning "Skipping existing $dest (use -Force to overwrite)"
        continue
      }

      $header = @(
        "# Extracted into module Private/"
        ("# Source: {0}:{1}-{2}" -f $f.Name, $fn.Extent.StartLineNumber, $fn.Extent.EndLineNumber)
        ""
      ) -join "`r`n"

      Set-Content -LiteralPath $dest -Encoding UTF8 -Value ($header + $fn.Extent.Text + "`r`n")
      $found += $fn.Name
    }
  }
}

Write-Host "✅ Extracted functions into $privateDir" -ForegroundColor Green
$found | Sort-Object -Unique | ForEach-Object { Write-Host "  $_" -ForegroundColor Cyan }

$missing = $FunctionNames | Where-Object { $found -notcontains $_ }
if ($missing) {
  Write-Warning "Not found (still in scripts): $($missing -join ', ')"
}