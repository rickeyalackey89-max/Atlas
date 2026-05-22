param(
  [string]$RunId = "latest",
  [string]$MlbRoot = "",
  [string]$DashboardRoot = "",
  [switch]$NoGit
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$defaultMlbRoot = Resolve-Path (Join-Path $scriptDir "..\..") | Select-Object -ExpandProperty Path
if ([string]::IsNullOrWhiteSpace($MlbRoot)) {
  $MlbRoot = $defaultMlbRoot
}
$MlbRoot = (Resolve-Path $MlbRoot).Path

if ([string]::IsNullOrWhiteSpace($DashboardRoot)) {
  if (-not [string]::IsNullOrWhiteSpace($env:ATLAS_DASHBOARD_ROOT)) {
    $DashboardRoot = $env:ATLAS_DASHBOARD_ROOT
  } else {
    $DashboardRoot = Join-Path (Split-Path -Parent $MlbRoot) "atlas-dashboard"
  }
}
$DashboardRoot = (Resolve-Path $DashboardRoot).Path

$builder = Join-Path $DashboardRoot "tools\build_mlb_dashboard_payload.py"
$publisher = Join-Path $DashboardRoot "publish-atlas.ps1"

if (-not (Test-Path -LiteralPath $builder)) {
  throw "Missing MLB dashboard payload builder: $builder"
}
if (-not (Test-Path -LiteralPath $publisher)) {
  throw "Missing dashboard publisher: $publisher"
}

Write-Host "[MLB LIVE PUBLISH] run_id=$RunId"
Write-Host "[MLB LIVE PUBLISH] mlb_root=$MlbRoot"
Write-Host "[MLB LIVE PUBLISH] dashboard_root=$DashboardRoot"

py $builder --mlb-root $MlbRoot --run-id $RunId
if ($LASTEXITCODE -ne 0) {
  throw "MLB dashboard payload build failed with exit code $LASTEXITCODE"
}

$publishArgs = @(
  "-NoProfile",
  "-ExecutionPolicy", "RemoteSigned",
  "-File", $publisher,
  "-Sport", "mlb",
  "-AtlasRoot", $MlbRoot
)
if ($NoGit) {
  $publishArgs += "-NoGit"
}

& powershell.exe @publishArgs
if ($LASTEXITCODE -ne 0) {
  throw "Dashboard publish failed with exit code $LASTEXITCODE"
}

Write-Host "[MLB LIVE PUBLISH] done"
