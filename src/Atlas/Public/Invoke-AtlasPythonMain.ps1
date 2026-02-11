function Invoke-AtlasPythonMain {
  [CmdletBinding(PositionalBinding = $false)]
  param(
    [string]$Python,
    [string]$VenvPath,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Args
  )

  Set-StrictMode -Version Latest
  $ErrorActionPreference = 'Stop'

  $repoRoot = Get-AtlasRepoRoot
  $py = Resolve-AtlasPython -Python $Python -VenvPath $VenvPath

  $main = Join-Path $repoRoot 'src\main.py'
  if (-not (Test-Path -LiteralPath $main)) { throw "Missing Python entry: $main" }

  # Use -- so args pass cleanly
  & $py $main @Args
}