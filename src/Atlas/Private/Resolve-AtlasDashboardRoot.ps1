function Resolve-AtlasDashboardRoot {
  [CmdletBinding()]
  param(
    [string]$DashboardRoot,
    [Parameter(Mandatory)]
    [string]$AtlasRoot
  )

  Set-StrictMode -Version Latest
  $ErrorActionPreference = 'Stop'

  if ($DashboardRoot) {
    if (-not (Test-Path -LiteralPath $DashboardRoot -PathType Container)) {
      throw "DashboardRoot not found: $DashboardRoot"
    }
    return (Resolve-Path -LiteralPath $DashboardRoot).Path
  }

  # Default: sibling repo next to Atlas: ..\AtlasDashboard
  $candidate = Join-Path (Split-Path -Parent $AtlasRoot) 'AtlasDashboard'
  if (Test-Path -LiteralPath $candidate -PathType Container) {
    return (Resolve-Path -LiteralPath $candidate).Path
  }

  throw "Could not locate AtlasDashboard. Provide -DashboardRoot explicitly. Tried: $candidate"
}