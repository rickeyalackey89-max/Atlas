[CmdletBinding(SupportsShouldProcess)]
param(
  [string]$RepoRoot = (Get-Location).Path,
  [switch]$VerboseSkips
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Normalize-Path([string]$p) { [IO.Path]::GetFullPath($p) }

$repo = Normalize-Path $RepoRoot

$pyFiles = Get-ChildItem -LiteralPath $repo -Recurse -File -Filter *.py -ErrorAction SilentlyContinue |
  Where-Object {
    $_.FullName -notmatch '\\.venv\\' -and
    $_.FullName -notmatch '\\__pycache__\\'
  }

$rxAssign     = [regex]'(?m)^\s*(PROJECT_ROOT|ROOT|repo_root)\s*=\s*Path\(__file__\)\.resolve\(\)\.parents\[\d+\]\s*$'
$rxPathImport = [regex]'(?m)^\s*from\s+pathlib\s+import\s+Path\s*$'
$rxHasHelper  = [regex]'(?m)^\s*def\s+find_repo_root\s*\('

$helperBlock = @'
def find_repo_root(start: Path) -> Path:
    p = start.resolve()
    for parent in [p] + list(p.parents):
        if (parent / "tools").is_dir() and (parent / "data").is_dir():
            return parent
    return start.resolve()
'@

$wouldPatch = 0
$patched = 0
$skipped = 0

foreach ($f in $pyFiles) {

  $text = $null
  try {
    $text = Get-Content -LiteralPath $f.FullName -Raw -ErrorAction Stop
  } catch {
    $skipped++
    if ($VerboseSkips) { Write-Warning "Skip (read failed): $($f.FullName) :: $($_.Exception.Message)" }
    continue
  }

  if ($null -eq $text) {
    $skipped++
    if ($VerboseSkips) { Write-Warning "Skip (null content): $($f.FullName)" }
    continue
  }

  $text = [string]$text

  if (-not $rxAssign.IsMatch($text)) { continue }
  if (-not $rxPathImport.IsMatch($text)) {
    $skipped++
    if ($VerboseSkips) { Write-Warning "Skip (no 'from pathlib import Path'): $($f.FullName)" }
    continue
  }

  $new = $text

  if (-not $rxHasHelper.IsMatch($new)) {
    $new = $rxPathImport.Replace(
      $new,
      { param($m) $m.Value + "`n`n" + $helperBlock.TrimEnd() },
      1
    )
  }

  $new = $rxAssign.Replace(
    $new,
    { param($m)
      $var = $m.Groups[1].Value
      "$var = find_repo_root(Path(__file__))"
    },
    1
  )

  if ($new -eq $text) { continue }

  $wouldPatch++

  $bak = "$($f.FullName).bak"
  if ($PSCmdlet.ShouldProcess($f.FullName, "Backup to $bak and eliminate parents[] root assignment")) {
    # In -WhatIf, ShouldProcess returns True but file operations still no-op.
    # That's fine; we still report WouldPatch accurately.
    Copy-Item -LiteralPath $f.FullName -Destination $bak -Force
    Set-Content -LiteralPath $f.FullName -Value $new -Encoding UTF8
    $patched++
  }
}

Write-Host "Would patch files: $wouldPatch" -ForegroundColor Cyan
Write-Host "Patched files:     $patched" -ForegroundColor Green
Write-Host "Skipped files:     $skipped" -ForegroundColor Yellow
Write-Host "Backups created as *.bak next to modified files." -ForegroundColor Yellow