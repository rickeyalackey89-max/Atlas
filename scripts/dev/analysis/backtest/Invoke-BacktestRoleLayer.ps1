[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$Start,   # YYYYMMDD
  [Parameter(Mandatory=$true)][string]$End,     # YYYYMMDD
  [int]$NSims = 20000,
  [int]$Seed = 1337
)

$ErrorActionPreference = 'Stop'

# Repo root is 4 levels up from: scripts/dev/analysis/backtest
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..\..')).Path

# Ensure src/ is importable (critical)
$src = Join-Path $repo 'src'
if (-not (Test-Path -LiteralPath $src -PathType Container)) {
  throw "Missing src folder at: $src"
}
$env:PYTHONPATH = "$src;$env:PYTHONPATH"

# Always call the ctx backtest script living alongside this ps1
$scriptPath = Join-Path $PSScriptRoot 'backtest_role_layer_ctx.py'
if (-not (Test-Path -LiteralPath $scriptPath -PathType Leaf)) {
  throw "Missing backtest script: $scriptPath"
}

# Prefer py -3, fall back to python
$py = Get-Command py -ErrorAction SilentlyContinue
if ($py) {
  $exe  = 'py'
  $args = @(
    '-3',
    $scriptPath,
    '--start', $Start,
    '--end',   $End,
    '--nsims', "$NSims",
    '--seed',  "$Seed"
  )
}
else {
  $python = Get-Command python -ErrorAction SilentlyContinue
  if (-not $python) { throw "No Python found (py or python)." }
  $exe  = 'python'
  $args = @(
    $scriptPath,
    '--start', $Start,
    '--end',   $End,
    '--nsims', "$NSims",
    '--seed',  "$Seed"
  )
}

Write-Host ("Backtest ROLE layer (CTX): {0} -> {1} (nsims={2}, seed={3})" -f $Start, $End, $NSims, $Seed) -ForegroundColor Cyan
Write-Host ("Python: {0}" -f $exe) -ForegroundColor DarkGray
Write-Host ("Script: {0}" -f $scriptPath) -ForegroundColor DarkGray
Write-Host ("PYTHONPATH: {0}" -f $env:PYTHONPATH) -ForegroundColor DarkGray

& $exe @args
if ($LASTEXITCODE -ne 0) {
  throw "Backtest failed with exit code $LASTEXITCODE"
}