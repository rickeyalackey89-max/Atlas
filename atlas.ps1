# atlas.ps1 (repo root) - canonical CLI entrypoint

[CmdletBinding(PositionalBinding = $false)]
param(
  [Parameter(Position = 0)]
  [ValidateSet('publish','today-export','live-publish','help')]
  [string]$Command = 'publish',

  [string]$AtlasRoot,
  [string]$DashboardRoot,

  [ValidateSet('pwsh','powershell')]
  [string]$Shell = 'pwsh',

  # Publish flags
  [switch]$SkipRefresh,
  [switch]$SkipDashboard,
  [switch]$OnlyExport,
  [switch]$SkipCloudflarePayload,

  # Model safety flags
  [switch]$SkipModel,
  [switch]$AllowModelRun,

  [Parameter(ValueFromRemainingArguments = $true)]
  [string[]]$Args
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

Import-Module (Join-Path $PSScriptRoot 'src\Atlas') -Force

# Forward *bound* parameters so switches like -OnlyExport stay switches
Invoke-Atlas @PSBoundParameters