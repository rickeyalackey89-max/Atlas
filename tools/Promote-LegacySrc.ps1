[CmdletBinding(SupportsShouldProcess)]
param(
  [string]$RepoRoot = (Get-Location).Path
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Ensure-Dir([string]$p) {
  if (-not (Test-Path -LiteralPath $p)) {
    New-Item -ItemType Directory -Path $p -Force | Out-Null
  }
}

$repo = [IO.Path]::GetFullPath($RepoRoot)
$srcRoot = Join-Path $repo "src"
$atlasRoot = Join-Path $srcRoot "Atlas"
$legacyRoot = Join-Path $atlasRoot "legacy"

if (-not (Test-Path -LiteralPath $srcRoot)) { throw "Missing src/: $srcRoot" }
Ensure-Dir $atlasRoot
Ensure-Dir $legacyRoot

# files directly under src/ (legacy flat modules)
$legacyFiles = @(
  Get-ChildItem -LiteralPath $srcRoot -File -Filter *.py -ErrorAction SilentlyContinue |
    Where-Object { $_.DirectoryName -eq $srcRoot }
)

if ($legacyFiles.Count -eq 0) {
  Write-Host "No legacy src/*.py files found at repo root src/." -ForegroundColor Green
  exit 0
}

Write-Host "Legacy src/*.py files to move: $($legacyFiles.Count)" -ForegroundColor Yellow
foreach ($f in $legacyFiles) {
  $dest = Join-Path $legacyRoot $f.Name

  if ($PSCmdlet.ShouldProcess($f.FullName, "Move to $dest")) {
    Move-Item -LiteralPath $f.FullName -Destination $dest -Force
  }
}

# Ensure packages are importable
$initAtlas = Join-Path $atlasRoot "__init__.py"
$initLegacy = Join-Path $legacyRoot "__init__.py"

if (-not (Test-Path -LiteralPath $initAtlas)) {
  if ($PSCmdlet.ShouldProcess($initAtlas, "Create")) { Set-Content -LiteralPath $initAtlas -Value "" -Encoding UTF8 }
}
if (-not (Test-Path -LiteralPath $initLegacy)) {
  if ($PSCmdlet.ShouldProcess($initLegacy, "Create")) { Set-Content -LiteralPath $initLegacy -Value "" -Encoding UTF8 }
}

Write-Host "Done. Next: search for 'import src.' or 'from src' and update imports." -ForegroundColor Green