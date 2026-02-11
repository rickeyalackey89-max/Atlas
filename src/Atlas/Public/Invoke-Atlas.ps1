function Invoke-Atlas {
  [CmdletBinding(PositionalBinding = $false)]
  param(
    [Parameter(Position = 0)]
    [ValidateSet('publish','today-export','live-publish','help')]
    [string]$Command = 'publish',

    [string]$AtlasRoot,
    [string]$DashboardRoot,

    [ValidateSet('pwsh','powershell')]
    [string]$Shell = 'pwsh',

    [switch]$SkipRefresh,
    [switch]$SkipDashboard,
    [switch]$OnlyExport,
    [switch]$SkipCloudflarePayload,

    [switch]$SkipModel,

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Args
  )

  Set-StrictMode -Version Latest
  $ErrorActionPreference = 'Stop'

  $AtlasRoot     = Resolve-AtlasRoot -AtlasRoot $AtlasRoot
  $DashboardRoot = Resolve-AtlasDashboardRoot -DashboardRoot $DashboardRoot -AtlasRoot $AtlasRoot

  switch ($Command) {
    'publish' {
      Invoke-AtlasRunAllAndPublish `
        -AtlasRoot $AtlasRoot `
        -DashboardRoot $DashboardRoot `
        -Shell $Shell `
        -SkipRefresh:$SkipRefresh `
        -SkipDashboard:$SkipDashboard `
        -OnlyExport:$OnlyExport `
        -SkipModel:$SkipModel `
        -SkipCloudflarePayload:$SkipCloudflarePayload `
        @Args
      return
    }

    'today-export' {
      Invoke-AtlasRunTodayAndExport -AtlasRoot $AtlasRoot -Shell $Shell @Args
      return
    }

    'live-publish' {
      Invoke-AtlasLiveFeedPublish -AtlasRoot $AtlasRoot -DashboardRoot $DashboardRoot -Shell $Shell -SkipDashboard:$SkipDashboard @Args
      return
    }

    'help' {
      @"
Atlas (canonical entry)

Usage:
  .\atlas.ps1 publish [args...]
  .\atlas.ps1 today-export [args...]
  .\atlas.ps1 live-publish [args...]

Publish flags:
  -SkipRefresh            Skip tools\refresh_nba_gamelogs.py
  -SkipCloudflarePayload  Skip tools\export_cloudflare_payload.py
  -SkipDashboard          Skip AtlasDashboard publish-atlas.ps1
  -OnlyExport             Run today-export + audit board + payload export, but do not publish dashboard
  -SkipModel              Do not run the model step

Examples:
  .\atlas.ps1 publish
  .\atlas.ps1 publish -OnlyExport
  .\atlas.ps1 publish -SkipModel
"@ | Write-Host
      return
    }
  }
}