function Invoke-AtlasRunAllAndPublish {
  [CmdletBinding(PositionalBinding = $false)]
  param(
    [Parameter(Mandatory)]
    [string]$AtlasRoot,

    [Parameter(Mandatory)]
    [string]$DashboardRoot,

    [ValidateSet('pwsh','powershell')]
    [string]$Shell = 'pwsh',

    [switch]$SkipRefresh,
    [switch]$SkipDashboard,
    [switch]$OnlyExport,
    [switch]$SkipCloudflarePayload,

    # Keep SkipModel (useful), but REMOVE AllowModelRun requirement
    [switch]$SkipModel,

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Args
  )

  Set-StrictMode -Version Latest
  $ErrorActionPreference = 'Stop'

  $py = Resolve-AtlasPython -AtlasRoot $AtlasRoot

  # ---------------------------
  # Refresh gamelogs
  # ---------------------------
  if (-not $SkipRefresh) {
    Write-Host "=== Atlas: Refresh gamelogs ==="
    Push-Location $AtlasRoot
    try {
      & $py (Join-Path $AtlasRoot 'tools\refresh_nba_gamelogs.py')
    } finally { Pop-Location }
  } else {
    Write-Host "=== Atlas: Refresh gamelogs (SKIPPED) ==="
  }

  # ---------------------------
  # Run model (RESTORED DEFAULT)
  # - OnlyExport always skips model
  # - SkipModel skips model
  # - Otherwise: run model like before
  # ---------------------------
  if ($OnlyExport -or $SkipModel) {
    Write-Host "=== Atlas: Run model (SKIPPED: OnlyExport/SkipModel) ===" -ForegroundColor Yellow
  }
  else {
    Write-Host "=== Atlas: Run model (System + Windfall) ==="
    Invoke-AtlasRunTodayAndExport -AtlasRoot $AtlasRoot -Shell $Shell
  }

  # ---------------------------
  # Rebuild audit board
  # ---------------------------
  Write-Host "=== Atlas: Rebuild audit_last5_board (AVG schema, final writer) ==="
  Push-Location $AtlasRoot
  try {
    & $py (Join-Path $AtlasRoot 'tools\build_audit_last5_board.py')
  } finally { Pop-Location }

  # ---------------------------
  # Export Cloudflare payload
  # ---------------------------
  if (-not $SkipCloudflarePayload) {
    Write-Host "=== Atlas: Export canonical Cloudflare payload ==="
    Push-Location $AtlasRoot
    try {
      & $py (Join-Path $AtlasRoot 'tools\export_cloudflare_payload.py')
    } finally { Pop-Location }
  } else {
    Write-Host "=== Atlas: Export canonical Cloudflare payload (SKIPPED) ==="
  }

  # ---------------------------
  # Dashboard publish
  # ---------------------------
  if ($OnlyExport) {
    Write-Host "=== AtlasDashboard: Publish to Cloudflare (SKIPPED: OnlyExport) ==="
    Write-Host "=== DONE ==="
    return
  }

  if ($SkipDashboard) {
    Write-Host "=== AtlasDashboard: Publish to Cloudflare (SKIPPED) ==="
    Write-Host "=== DONE ==="
    return
  }

  Write-Host "=== AtlasDashboard: Publish to Cloudflare ==="
  $publish = Join-Path $DashboardRoot 'publish-atlas.ps1'
  if (-not (Test-Path -LiteralPath $publish)) {
    throw "Missing dashboard publish script: $publish"
  }

  Push-Location $DashboardRoot
  try {
    & $Shell -NoProfile -ExecutionPolicy Bypass -File $publish -AtlasRoot $AtlasRoot
  } finally { Pop-Location }

  Write-Host "=== DONE ==="
}