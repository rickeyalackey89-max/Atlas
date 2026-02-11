<#
.SYNOPSIS
  Audits Atlas Python scripts and proposes consolidation actions.

.DESCRIPTION
  Scans scripts/ and tools/ for .py files, classifies them, produces reports, and optionally applies actions:
    - Move to tools/
    - Move to src/<package>/
    - Quarantine to scripts/dev/
    - Delete (safe: moves to .trash by default unless -HardDelete)

  Designed to reduce "mixed helpers" and make runtime vs dev explicit.

.PARAMETER RepoRoot
  Root of the Atlas repo. Defaults to current directory.

.PARAMETER ScriptsDir
  Relative path to scripts directory. Defaults to "scripts".

.PARAMETER ToolsDir
  Relative path to tools directory. Defaults to "tools".

.PARAMETER SrcDir
  Relative path to src directory. Defaults to "src".

.PARAMETER PackageName
  Python package folder name under src/. Defaults to "atlas".

.PARAMETER ReportDir
  Output folder for reports. Defaults to ".atlas_audit".

.PARAMETER Mode
  What to do:
    - ReportOnly: just generate reports
    - Interactive: prompt decisions per file and write a plan file
    - ApplyPlan: apply a previously generated plan file

.PARAMETER PlanPath
  Path to plan JSON created in Interactive mode.

.PARAMETER HardDelete
  Actually deletes files when action is Delete. Otherwise moves to .trash/

.PARAMETER Force
  Overwrite existing destination files by appending a numeric suffix.
#>

[CmdletBinding()]
param(
  [Parameter()] [string] $RepoRoot = (Get-Location).Path,
  [Parameter()] [string] $ScriptsDir = "scripts",
  [Parameter()] [string] $ToolsDir   = "tools",
  [Parameter()] [string] $SrcDir     = "src",
  [Parameter()] [string] $PackageName = "atlas",
  [Parameter()] [string] $ReportDir  = ".atlas_audit",
  [Parameter()] [ValidateSet("ReportOnly","Interactive","ApplyPlan")] [string] $Mode = "ReportOnly",
  [Parameter()] [string] $PlanPath,
  [Parameter()] [switch] $HardDelete,
  [Parameter()] [switch] $Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Ensure-Dir([string]$path) {
  if (-not (Test-Path -LiteralPath $path)) {
    New-Item -ItemType Directory -Path $path | Out-Null
  }
}

function Resolve-RepoPath([string]$root, [string]$relative) {
  $p = Join-Path $root $relative
  if (-not (Test-Path -LiteralPath $p)) {
    return $p  # allow missing paths; caller decides
  }
  return (Resolve-Path -LiteralPath $p).Path
}

function Read-Text([string]$path) {
  return Get-Content -LiteralPath $path -Raw -ErrorAction Stop
}

function Get-Imports([string]$text) {
  $imports = New-Object System.Collections.Generic.HashSet[string]
  foreach ($m in [regex]::Matches(
    $text,
    '^\s*(?:from\s+([a-zA-Z0-9_\.]+)\s+import|import\s+([a-zA-Z0-9_\.]+))',
    [System.Text.RegularExpressions.RegexOptions]::Multiline
  )) {
    $mod = if ($m.Groups[1].Success) { $m.Groups[1].Value } else { $m.Groups[2].Value }
    if ($null -ne $mod -and $mod.Trim().Length -gt 0) { [void]$imports.Add($mod.Trim()) }
  }
  return $imports
}

function Get-EntryPointSignals([string]$text) {
  return @{
    HasMainGuard = ($text -match '__name__\s*==\s*[''"]__main__[''"]')
    UsesArgparse = ($text -match '\bargparse\b')
    UsesTyper    = ($text -match '\btyper\b')
    UsesClick    = ($text -match '\bclick\b')
  }
}

function Get-AtlasSignals([string]$text, [string]$packageName) {
  return @{
    ReferencesTools = ($text -match '(\btools\b|from\s+tools\b|import\s+tools\b)')
    ReferencesSrc   = ($text -match '(\bsrc\b|from\s+src\b|import\s+src\b)')
    ReferencesAtlas = ($text -match "(\b$packageName\b|from\s+$packageName\b|import\s+$packageName\b)")
    HasModelWords   = ($text -match '\b(model|training|inference|predict|forecast|fit|torch|sklearn|xgboost|lightgbm)\b')
    HasIOWords      = ($text -match '\b(csv|json|parquet|s3|blob|filesystem|pathlib|open\(|read_\w+|write_\w+)\b')
    HasPublishWords = ($text -match '\b(publish|upload|report|markdown|pdf|email|slack|teams|sharepoint)\b')
    HasNetworkWords = ($text -match '\b(requests|httpx|urllib|aiohttp)\b')
  }
}

function Classify-Script([string]$path, [string]$text, [string]$packageName, [string]$repoRootResolved) {
  $imports = Get-Imports $text
  $ep  = Get-EntryPointSignals $text
  $sig = Get-AtlasSignals -text $text -packageName $packageName

  $scoreRuntimeHelper = 0
  $scoreModelLogic    = 0
  $scoreOneOff        = 0
  $scoreFuture        = 0

  if ($ep.HasMainGuard -or $ep.UsesArgparse -or $ep.UsesTyper -or $ep.UsesClick) { $scoreOneOff += 2 }
  if ($sig.ReferencesTools -or $sig.ReferencesAtlas) { $scoreRuntimeHelper += 2 }
  if ($sig.HasModelWords)   { $scoreModelLogic += 2 }
  if ($sig.HasPublishWords) { $scoreRuntimeHelper += 1 }
  if ($sig.HasIOWords)      { $scoreRuntimeHelper += 1 }

  $todoCount = ([regex]::Matches($text, '\bTODO\b')).Count
  if ($todoCount -ge 5) { $scoreFuture += 2 }
  if ($text -match '\b(WIP|work\s*in\s*progress|stub|placeholder)\b') { $scoreFuture += 2 }

  if (($ep.HasMainGuard -or $ep.UsesArgparse -or $ep.UsesTyper -or $ep.UsesClick) -and
      -not ($sig.ReferencesTools -or $sig.ReferencesAtlas -or $sig.ReferencesSrc)) {
    $scoreOneOff += 2
  }

  if ($sig.HasModelWords -and ($sig.ReferencesAtlas -or $sig.ReferencesSrc)) { $scoreModelLogic += 2 }
  if ($sig.ReferencesTools -or $sig.ReferencesAtlas) { $scoreRuntimeHelper += 1 }

  $scores = @{
    "RuntimeDependency" = $scoreRuntimeHelper
    "ModelLogic"        = $scoreModelLogic
    "OneOffUtility"     = $scoreOneOff
    "FutureFeature"     = $scoreFuture
  }

  $best = $scores.GetEnumerator() | Sort-Object Value -Descending | Select-Object -First 1
  $label = [string]$best.Key
  $confidence = [int]$best.Value
  if ($confidence -lt 2) { $label = "OneOffUtility" }

  $reasons = New-Object System.Collections.Generic.List[string]
  if ($ep.HasMainGuard)     { $reasons.Add("has __main__ guard") }
  if ($ep.UsesArgparse)     { $reasons.Add("uses argparse") }
  if ($sig.ReferencesTools) { $reasons.Add("imports/ref tools") }
  if ($sig.ReferencesAtlas) { $reasons.Add("imports/ref package") }
  if ($sig.HasModelWords)   { $reasons.Add("model keywords") }
  if ($sig.HasPublishWords) { $reasons.Add("publish keywords") }
  if ($todoCount -ge 5)     { $reasons.Add("many TODOs ($todoCount)") }

  $rel = $path
  if ($repoRootResolved -and $path.StartsWith($repoRootResolved, [System.StringComparison]::OrdinalIgnoreCase)) {
    $rel = $path.Substring($repoRootResolved.Length).TrimStart('\','/')
  }

  return [pscustomobject]@{
    Path     = $path
    RelPath  = $rel
    FileName = [IO.Path]::GetFileName($path)
    Label    = $label
    Score    = $confidence
    Imports  = ($imports | Sort-Object) -join "; "
    Reasons  = ($reasons -join ", ")
  }
}

function New-UniquePath([string]$destPath) {
  if (-not (Test-Path -LiteralPath $destPath)) { return $destPath }
  if (-not $Force) {
    throw "Destination exists: $destPath (use -Force to auto-suffix)"
  }
  $dir  = Split-Path -Parent $destPath
  $name = [IO.Path]::GetFileNameWithoutExtension($destPath)
  $ext  = [IO.Path]::GetExtension($destPath)
  for ($i = 1; $i -le 999; $i++) {
    $candidate = Join-Path $dir ("{0}.{1}{2}" -f $name, $i, $ext)
    if (-not (Test-Path -LiteralPath $candidate)) { return $candidate }
  }
  throw "Could not find available filename for $destPath"
}

function Write-Reports($items, [string]$outDir) {
  Ensure-Dir $outDir
  $csvPath = Join-Path $outDir "scripts_audit.csv"
  $mdPath  = Join-Path $outDir "scripts_audit.md"

  $items | Sort-Object Label, RelPath | Export-Csv -NoTypeInformation -Path $csvPath

  $groups = $items | Group-Object Label
  $md = New-Object System.Collections.Generic.List[string]
  $md.Add("# Atlas audit") | Out-Null
  $md.Add("") | Out-Null
  $md.Add("Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')") | Out-Null
  $md.Add("") | Out-Null

  foreach ($g in ($groups | Sort-Object Name)) {
    $md.Add("## $($g.Name) ($($g.Count))") | Out-Null
    $md.Add("") | Out-Null
    $md.Add("| Path | Score | Reasons |") | Out-Null
    $md.Add("|---|---:|---|") | Out-Null

    foreach ($it in ($g.Group | Sort-Object RelPath)) {
      $reasonsSafe = ([string]$it.Reasons) -replace '\|','\|'
      $pathCell = '`' + $it.RelPath + '`'
      $row = '| ' + $pathCell + ' | ' + $it.Score + ' | ' + $reasonsSafe + ' |'
      $md.Add($row) | Out-Null
    }
    $md.Add("") | Out-Null
  }

  Set-Content -LiteralPath $mdPath -Value ($md -join "`n") -Encoding UTF8

  Write-Host "Wrote reports:" -ForegroundColor Green
  Write-Host "  $csvPath"
  Write-Host "  $mdPath"
}

function Build-PlanInteractive($items, [string]$outDir, [string]$packageName) {
  Ensure-Dir $outDir
  $plan = [System.Collections.Generic.List[object]]::new()

  Write-Host ""
  Write-Host "Interactive classification. For each file, choose an action:" -ForegroundColor Cyan
  Write-Host "  [T] Move to tools/      [S] Move to src/$packageName/     [Q] Quarantine to scripts/dev/" -ForegroundColor Cyan
  Write-Host "  [D] Delete (to .trash/) [K] Keep as-is                   [X] Skip remaining" -ForegroundColor Cyan
  Write-Host ""

  $skipAll = $false
  foreach ($it in ($items | Sort-Object Label, RelPath)) {
    if ($skipAll) { break }

    Write-Host "File: $($it.RelPath)" -ForegroundColor Yellow
    Write-Host "  Suggested: $($it.Label) (score $($it.Score)) — $($it.Reasons)"
    $choice = Read-Host "Action [T/S/Q/D/K/X]"
    $choice = $choice.Trim().ToUpperInvariant()

    if ($choice -eq "X") { $skipAll = $true; break }

    $action = switch ($choice) {
      "T" { "MoveToTools" }
      "S" { "MoveToSrc" }
      "Q" { "QuarantineDev" }
      "D" { "Delete" }
      "K" { "Keep" }
      default { "Keep" }
    }

    $plan.Add([pscustomobject]@{
      Path   = $it.Path
      Action = $action
      Note   = "Suggested=$($it.Label); Reasons=$($it.Reasons)"
    }) | Out-Null

    Write-Host ""
  }

  $planPath = Join-Path $outDir "plan.json"
  $plan | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $planPath -Encoding UTF8
  Write-Host "Saved plan: $planPath" -ForegroundColor Green
  return $planPath
}

function Apply-Plan(
  [string]$planPath,
  [string]$repoRootResolved,
  [string]$toolsResolved,
  [string]$srcPkgResolved,
  [string]$scriptsResolved
) {
  if (-not (Test-Path -LiteralPath $planPath)) { throw "Plan not found: $planPath" }
  $plan = Get-Content -LiteralPath $planPath -Raw | ConvertFrom-Json

  $trashDir = Join-Path $repoRootResolved ".trash"
  $devDir   = Join-Path $scriptsResolved "dev"

  Ensure-Dir $trashDir
  Ensure-Dir $devDir
  Ensure-Dir $toolsResolved
  Ensure-Dir $srcPkgResolved

  foreach ($item in $plan) {
    $path   = [string]$item.Path
    $action = [string]$item.Action

    if (-not (Test-Path -LiteralPath $path)) {
      Write-Warning "Missing, skipping: $path"
      continue
    }

    switch ($action) {
      "MoveToTools" {
        $dest = Join-Path $toolsResolved ([IO.Path]::GetFileName($path))
        $dest = New-UniquePath $dest
        Move-Item -LiteralPath $path -Destination $dest
        Write-Host "Moved → tools/: $path -> $dest" -ForegroundColor Green
      }
      "MoveToSrc" {
        $dest = Join-Path $srcPkgResolved ([IO.Path]::GetFileName($path))
        $dest = New-UniquePath $dest
        Move-Item -LiteralPath $path -Destination $dest
        Write-Host "Moved → src/: $path -> $dest" -ForegroundColor Green
      }
      "QuarantineDev" {
        $dest = Join-Path $devDir ([IO.Path]::GetFileName($path))
        $dest = New-UniquePath $dest
        Move-Item -LiteralPath $path -Destination $dest
        Write-Host "Quarantined → scripts/dev/: $path -> $dest" -ForegroundColor Green
      }
      "Delete" {
        if ($HardDelete) {
          Remove-Item -LiteralPath $path -Force
          Write-Host "Deleted: $path" -ForegroundColor Red
        } else {
          $dest = Join-Path $trashDir ([IO.Path]::GetFileName($path))
          $dest = New-UniquePath $dest
          Move-Item -LiteralPath $path -Destination $dest
          Write-Host "Trashed → .trash/: $path -> $dest" -ForegroundColor DarkYellow
        }
      }
      "Keep" {
        Write-Host "Kept: $path" -ForegroundColor DarkGray
      }
      default {
        Write-Warning "Unknown action '$action' for $path"
      }
    }
  }
}

# --- Main ---
$repoRootResolved = (Resolve-Path -LiteralPath $RepoRoot).Path

$scriptsResolved = Resolve-RepoPath -root $repoRootResolved -relative $ScriptsDir
$toolsResolved   = Resolve-RepoPath -root $repoRootResolved -relative $ToolsDir
$srcResolved     = Resolve-RepoPath -root $repoRootResolved -relative $SrcDir
$srcPkgResolved  = Join-Path $srcResolved $PackageName
$reportResolved  = Join-Path $repoRootResolved $ReportDir

Ensure-Dir $reportResolved

# Collect python files from scripts/ + tools/ (exclude scripts/dev)
$scanRoots = @($scriptsResolved, $toolsResolved)
$pyFiles = New-Object System.Collections.Generic.List[System.IO.FileInfo]

foreach ($root in $scanRoots) {
  if (Test-Path -LiteralPath $root) {
    foreach ($f in (Get-ChildItem -LiteralPath $root -Recurse -File -Filter *.py)) {
      if ($f.FullName -notmatch '\\scripts\\dev\\') {
        $pyFiles.Add($f) | Out-Null
      }
    }
  }
}

# Build items (STRICTMODE SAFE)
$items = @()
foreach ($f in ($pyFiles | Sort-Object FullName)) {
  $text = Read-Text $f.FullName
  $items += Classify-Script -path $f.FullName -text $text -packageName $PackageName -repoRootResolved $repoRootResolved
}

Write-Reports -items $items -outDir $reportResolved

switch ($Mode) {
  "ReportOnly" {
    Write-Host "Done (report only)." -ForegroundColor Cyan
  }
  "Interactive" {
    $planPathOut = Build-PlanInteractive -items $items -outDir $reportResolved -packageName $PackageName
    Write-Host "Next: run with -Mode ApplyPlan -PlanPath `"$planPathOut`"" -ForegroundColor Cyan
  }
  "ApplyPlan" {
    if (-not $PlanPath) { throw "Provide -PlanPath for ApplyPlan mode." }
    Apply-Plan -planPath (Resolve-Path -LiteralPath $PlanPath).Path `
      -repoRootResolved $repoRootResolved `
      -toolsResolved $toolsResolved `
      -srcPkgResolved $srcPkgResolved `
      -scriptsResolved $scriptsResolved
    Write-Host "Done (plan applied)." -ForegroundColor Cyan
  }
}