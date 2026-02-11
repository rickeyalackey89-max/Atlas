function Get-AtlasRepoRoot {
  [CmdletBinding()]
  param()

  Set-StrictMode -Version Latest
  $ErrorActionPreference = 'Stop'

  # This module lives at: <repo>\src\Atlas
  # So repo root is three levels up from Public/Private files: <repo>
  $repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..\..\..')  # Public/Private => Atlas => src => repo
  return $repoRoot.Path
}