#requires -Version 7.0
<#
.SYNOPSIS
  Analyzes *.bak files and compares them to their non-.bak counterpart.

.OUTPUT
  - Prints summary to console
  - Writes CSV report to scripts/dev/admin/bak_report.csv
  - Writes a text list of "needs review" to scripts/dev/admin/bak_needs_review.txt

USAGE
  pwsh scripts/dev/admin/Analyze-BakFiles.ps1
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-RepoRoot {
  param([string]$Start = (Get-Location).Path)

  $startPath = (Resolve-Path -LiteralPath $Start).Path
  $dir = [System.IO.DirectoryInfo]::new($startPath)

  function Test-AtlasRoot([string]$p) {
    return (
      (Test-Path -LiteralPath (Join-Path $p "run_today.py") -PathType Leaf) -or
      (Test-Path -LiteralPath (Join-Path $p "tools") -PathType Container) -or
      (Test-Path -LiteralPath (Join-Path $p "src\Atlas") -PathType Container) -or
      (Test-Path -LiteralPath (Join-Path $p "scripts\dev") -PathType Container)
    )
  }

  while ($dir -ne $null) {
    if (Test-AtlasRoot $dir.FullName) { return $dir.FullName }
    $dir = $dir.Parent
  }

  # Final fallback: assume Start is the root (better than throwing)
  return $startPath
}

function Get-TextFileHash {
  param([string]$Path)
  # Hash normalized text to avoid false diffs from line endings
  $txt = Get-Content -LiteralPath $Path -Raw -ErrorAction Stop
  $txt = $txt -replace "`r`n", "`n"
  $bytes = [System.Text.Encoding]::UTF8.GetBytes($txt)
  $sha = [System.Security.Cryptography.SHA256]::Create()
  try {
    ($sha.ComputeHash($bytes) | ForEach-Object { $_.ToString("x2") }) -join ""
  } finally {
    $sha.Dispose()
  }
}

$root = Get-RepoRoot
Push-Location $root
try {
  $outDir = Join-Path $root "scripts\dev\admin"
  if (-not (Test-Path $outDir)) { New-Item -ItemType Directory -Path $outDir | Out-Null }

  $reportCsv = Join-Path $outDir "bak_report.csv"
  $needsReview = Join-Path $outDir "bak_needs_review.txt"

  $bakFiles = Get-ChildItem -Path $root -Recurse -File -Filter *.bak |
    Where-Object { $_.FullName -notmatch '\\(\.git|\.venv|venv|__pycache__|build|dist)\b' } |
    Sort-Object FullName

  if ($bakFiles.Count -eq 0) {
    Write-Host "No *.bak files found." -ForegroundColor Green
    return
  }

  $rows = foreach ($bak in $bakFiles) {
    $livePath = $bak.FullName -replace '\.bak$', ''
    $liveExists = Test-Path -LiteralPath $livePath -PathType Leaf

    $bakHash = Get-TextFileHash -Path $bak.FullName
    $liveHash = $null
    $same = $false
    if ($liveExists) {
      $liveHash = Get-TextFileHash -Path $livePath
      $same = ($bakHash -eq $liveHash)
    }

    $status =
      if (-not $liveExists) { "MISSING_LIVE" }
      elseif ($same) { "IDENTICAL" }
      else { "DIFFERS" }

    $newer =
      if (-not $liveExists) { $true }
      else { $bak.LastWriteTime -gt (Get-Item -LiteralPath $livePath).LastWriteTime }

    [pscustomobject]@{
      BakPath         = $bak.FullName
      LivePath        = $livePath
      LiveExists      = $liveExists
      Status          = $status
      BakLastWrite    = $bak.LastWriteTime
      LiveLastWrite   = if ($liveExists) { (Get-Item -LiteralPath $livePath).LastWriteTime } else { $null }
      BakBytes        = $bak.Length
      LiveBytes       = if ($liveExists) { (Get-Item -LiteralPath $livePath).Length } else { $null }
      BakHash         = $bakHash
      LiveHash        = $liveHash
      BakIsNewer      = $newer
    }
  }

  $rows | Export-Csv -NoTypeInformation -Encoding UTF8 -Path $reportCsv

 $review = $rows |
  Where-Object { $_.Status -ne "IDENTICAL" } |
  Sort-Object `
    @{Expression = 'Status'; Ascending = $true},
    @{Expression = 'BakIsNewer'; Ascending = $false},
    @{Expression = 'BakLastWrite'; Ascending = $false}

  $reviewLines = $review | ForEach-Object {
    "{0}`n  LIVE: {1}`n  STATUS: {2} | BAK_NEWER: {3}`n" -f $_.BakPath, $_.LivePath, $_.Status, $_.BakIsNewer
  }
  $reviewLines | Set-Content -Encoding UTF8 -Path $needsReview

  Write-Host "Wrote report:" -ForegroundColor Cyan
  Write-Host "  $reportCsv"
  Write-Host "  $needsReview"
  Write-Host ""

  $counts = $rows | Group-Object Status | Sort-Object Name
  Write-Host "Summary:" -ForegroundColor Cyan
  $counts | ForEach-Object { Write-Host ("  {0,-12} {1,5}" -f $_.Name, $_.Count) }

  Write-Host ""
  Write-Host "Next: use git diff on DIFFERS / MISSING_LIVE items listed in bak_needs_review.txt" -ForegroundColor Yellow
}
finally {
  Pop-Location
}