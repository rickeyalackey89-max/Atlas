[CmdletBinding()]
param(
  # Root of the Atlas repo
  [string]$AtlasRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path,

  # Actually perform deletes / moves
  [switch]$Apply,

  # After a successful run, permanently delete quarantined files
  [switch]$PurgeQuarantine
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Info($m) { Write-Host $m -ForegroundColor Cyan }
function Warn($m) { Write-Host $m -ForegroundColor Yellow }

$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$quarantineRoot = Join-Path $AtlasRoot "ops\quarantine_$stamp"

# ------------------------------------------------------------------
# DEFINITIVE KEEP LIST (execution-critical)
# ------------------------------------------------------------------
$keepRoots = @(
  'atlas.ps1',
  'run_today.py',
  'requirements.txt',
  'src',
  'tools',
  'scripts',
  'data'
)

function IsUnderKeepRoot([string]$fullPath) {
  $rel = (Resolve-Path $fullPath).Path.Substring($AtlasRoot.Length).TrimStart('\','/')
  foreach ($k in $keepRoots) {
    if ($rel -eq $k) { return $true }
    if ($rel.StartsWith("$k\")) { return $true }
  }
  return $false
}

Info "=== Atlas Clean Plan ==="
Info "AtlasRoot: $AtlasRoot"
Info "QuarantineRoot: $quarantineRoot"
Write-Host ""

# ------------------------------------------------------------------
# 1) HARD DELETE: always-safe generated junk
# ------------------------------------------------------------------
Info "Deleting generated junk (safe):"

$deleteTargets = @()

# logs/
$deleteTargets += Join-Path $AtlasRoot 'logs'

# data/cache/
$deleteTargets += Join-Path $AtlasRoot 'data\cache'

# __pycache__ directories
$deleteTargets += Get-ChildItem -LiteralPath $AtlasRoot -Directory -Recurse -Force -ErrorAction SilentlyContinue |
  Where-Object { $_.Name -eq '__pycache__' } |
  Select-Object -ExpandProperty FullName

# *.pyc / *.pyo
$deleteTargets += Get-ChildItem -LiteralPath $AtlasRoot -File -Recurse -Force -ErrorAction SilentlyContinue |
  Where-Object { $_.Extension -in @('.pyc','.pyo') } |
  Select-Object -ExpandProperty FullName

$deleteTargets = $deleteTargets | Sort-Object -Unique

foreach ($p in $deleteTargets) {
  if ($Apply) {
    if (Test-Path $p) {
      Remove-Item -LiteralPath $p -Recurse -Force -ErrorAction SilentlyContinue
      Warn "DELETED: $p"
    }
  } else {
    Write-Host "DRYRUN delete: $p"
  }
}

# ------------------------------------------------------------------
# 2) QUARANTINE: noise files (docs, notes, ad-hoc utilities)
# ------------------------------------------------------------------
Info ""
Info "Quarantining non-execution noise (.md / .txt / stray root scripts)"

$files = Get-ChildItem -LiteralPath $AtlasRoot -File -Recurse -Force -ErrorAction SilentlyContinue |
  Where-Object {
    $_.FullName -notmatch '\\ops\\quarantine_\d{8}_\d{6}\\'
  }

$toQuarantine = New-Object System.Collections.Generic.List[string]

foreach ($f in $files) {
  $rel = $f.FullName.Substring($AtlasRoot.Length).TrimStart('\','/')
  $ext = $f.Extension.ToLowerInvariant()

 # Docs/notes are quarantine targets EXCEPT:
# - requirements.txt (needed for environment)
# - data/input + data/output (these are I/O assets)
if ($ext -in @('.md','.txt')) {
  $relLower = $rel.ToLowerInvariant()

  if ($relLower -eq 'requirements.txt') { continue }
  if ($relLower.StartsWith('data\input\') -or $relLower.StartsWith('data\output\')) { continue }

  $toQuarantine.Add($f.FullName) | Out-Null
  continue
}

  # Root-level ad-hoc python or ps1 scripts (not under keep roots)
  if ($ext -in @('.py','.ps1') -and -not (IsUnderKeepRoot $f.FullName)) {
    $toQuarantine.Add($f.FullName) | Out-Null
    continue
  }
}

$toQuarantine = $toQuarantine | Sort-Object -Unique

if (-not $toQuarantine -or @($toQuarantine).Count -eq 0) {
  Info "Nothing to quarantine."
}

else {
  if ($Apply) {
    New-Item -ItemType Directory -Force -Path $quarantineRoot | Out-Null
  }

  foreach ($src in $toQuarantine) {
    $rel = (Resolve-Path $src).Path.Substring($AtlasRoot.Length).TrimStart('\','/')
    $dest = Join-Path $quarantineRoot $rel
    $destDir = Split-Path $dest -Parent

    if ($Apply) {
      New-Item -ItemType Directory -Force -Path $destDir | Out-Null
      Move-Item -LiteralPath $src -Destination $dest -Force
      Warn "QUARANTINED: $rel"
    } else {
      Write-Host "DRYRUN move: $rel  ->  ops\quarantine_$stamp\$rel"
    }
  }
}

# ------------------------------------------------------------------
# 3) OPTIONAL: purge all quarantines (irreversible)
# ------------------------------------------------------------------
if ($PurgeQuarantine) {
  Info ""
  Warn "PURGE MODE: deleting ALL quarantine folders under ops\"

  $qRoots = Get-ChildItem -LiteralPath (Join-Path $AtlasRoot 'ops') -Directory -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -like 'quarantine_*' }

  foreach ($q in $qRoots) {
    if ($Apply) {
      Remove-Item -LiteralPath $q.FullName -Recurse -Force
      Warn "PURGED: $($q.FullName)"
    } else {
      Write-Host "DRYRUN delete quarantine: $($q.FullName)"
    }
  }
}

Write-Host ""
Info "Done."
Info "Apply with:  .\tools\Clean-Atlas.ps1 -Apply"
Info "After a successful run, permanently delete quarantines with:"
Info "  .\tools\Clean-Atlas.ps1 -Apply -PurgeQuarantine"