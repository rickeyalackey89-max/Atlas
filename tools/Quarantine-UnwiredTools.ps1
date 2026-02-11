[CmdletBinding(SupportsShouldProcess)]
param(
  [string]$RepoRoot = (Get-Location).Path,
  [string]$Runner   = "run_today.py",
  [string]$ToolsDir = "tools",
  [string]$QuarantineDir = "scripts/dev/tools_quarantine"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Normalize-Path([string]$p) { [IO.Path]::GetFullPath($p) }

$repo = Normalize-Path $RepoRoot

$runnerPath = Join-Path $repo $Runner
if (-not (Test-Path -LiteralPath $runnerPath)) { throw "Runner not found: $runnerPath" }

$toolsPath = Join-Path $repo $ToolsDir
if (-not (Test-Path -LiteralPath $toolsPath)) { throw "tools/ dir not found: $toolsPath" }

$quarantinePath = Join-Path $repo $QuarantineDir
if (-not (Test-Path -LiteralPath $quarantinePath)) {
  New-Item -ItemType Directory -Path $quarantinePath -Force | Out-Null
}

# Extract wiring from run_today.py
$runnerText = Get-Content -LiteralPath $runnerPath -Raw
$rx = [regex]'TOOLS_DIR\s*/\s*"([^"]+\.py)"'
$wiredRel = @(
  foreach ($m in $rx.Matches($runnerText)) { $m.Groups[1].Value }
) | Sort-Object -Unique

$wiredSet = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
foreach ($w in $wiredRel) {
  [void]$wiredSet.Add((Normalize-Path (Join-Path $toolsPath $w)))
}

$toolFiles = Get-ChildItem -LiteralPath $toolsPath -Recurse -File -Filter *.py -ErrorAction SilentlyContinue |
  Where-Object { $_.FullName -notmatch '\\__pycache__\\' }

$unwired = @(
  foreach ($f in $toolFiles) {
    $full = Normalize-Path $f.FullName
    if (-not $wiredSet.Contains($full)) { $f }
  }
)

if ($unwired.Count -eq 0) {
  Write-Host "No unwired tools found in tools/." -ForegroundColor Green
  exit 0
}

Write-Host "Unwired tools to quarantine: $($unwired.Count)" -ForegroundColor Yellow
foreach ($f in $unwired) {
  $dest = Join-Path $quarantinePath $f.Name

  # Avoid filename collisions in quarantine
  if (Test-Path -LiteralPath $dest) {
    $base = [IO.Path]::GetFileNameWithoutExtension($f.Name)
    $ext  = [IO.Path]::GetExtension($f.Name)
    $i = 1
    do {
      $dest = Join-Path $quarantinePath ("{0}__{1}{2}" -f $base, $i, $ext)
      $i++
    } while (Test-Path -LiteralPath $dest)
  }

  if ($PSCmdlet.ShouldProcess($f.FullName, "Move to $dest")) {
    Move-Item -LiteralPath $f.FullName -Destination $dest -Force
  }
}

Write-Host "Done. Run strict wiring audit to confirm invariants." -ForegroundColor Green
exit 0
