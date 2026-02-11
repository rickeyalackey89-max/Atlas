function Invoke-AtlasLiveFeedPublish {
  [CmdletBinding(PositionalBinding = $false)]
  param(
    [Parameter(Mandatory)]
    [string]$AtlasRoot,

    [Parameter(Mandatory)]
    [string]$DashboardRoot,

    [ValidateSet('pwsh','powershell')]
    [string]$Shell = 'pwsh',

    [switch]$SkipDashboard,

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Args
  )

  Set-StrictMode -Version Latest
  $ErrorActionPreference = 'Stop'

  Write-Host ""
  Write-Host "==============================="
  Write-Host "[ATLAS today-export] $((Get-Date).ToString('yyyy-MM-dd HH:mm:ss'))"
  Write-Host "==============================="

  Invoke-AtlasRunTodayAndExport -AtlasRoot $AtlasRoot -Shell $Shell

  if ($SkipDashboard) {
    Write-Host ""
    Write-Host "==============================="
    Write-Host "[DASHBOARD publish-atlas] SKIPPED"
    Write-Host "==============================="
    return
  }

  Write-Host ""
  Write-Host "==============================="
  Write-Host "[DASHBOARD publish-atlas] $((Get-Date).ToString('yyyy-MM-dd HH:mm:ss'))"
  Write-Host "==============================="

  $publish = Join-Path $DashboardRoot 'publish-atlas.ps1'
  if (-not (Test-Path -LiteralPath $publish)) { throw "Missing dashboard publish script: $publish" }

  Push-Location $DashboardRoot
  try {
    & $Shell -NoProfile -ExecutionPolicy Bypass -File $publish -AtlasRoot $AtlasRoot
  } finally { Pop-Location }
}