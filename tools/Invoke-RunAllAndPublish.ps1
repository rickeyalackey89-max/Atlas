function Invoke-RunAllAndPublish {
  [CmdletBinding(PositionalBinding=$false)]
  param(
    [Parameter(ValueFromRemainingArguments=$true)]
    [string[]]$Args
  )

  Set-StrictMode -Version Latest
  $ErrorActionPreference = 'Stop'

  $script = Join-Path $PSScriptRoot '..\..\..\run_all_and_publish.ps1'
  & $script @Args
}