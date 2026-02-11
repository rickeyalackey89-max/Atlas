function Resolve-AtlasRoot {
  [CmdletBinding()]
  param(
    [string]$AtlasRoot
  )

  Set-StrictMode -Version Latest
  $ErrorActionPreference = 'Stop'

  if ($AtlasRoot) {
    if (-not (Test-Path -LiteralPath $AtlasRoot -PathType Container)) {
      throw "AtlasRoot not found: $AtlasRoot"
    }
    return (Resolve-Path -LiteralPath $AtlasRoot).Path
  }

  # Module lives in <repo>\src\Atlas
  $repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..\..\..')
  return $repoRoot.Path
}