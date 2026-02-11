function Invoke-RunTodayAndExport {
  [CmdletBinding(PositionalBinding=$false)]
  param(
    [Parameter(ValueFromRemainingArguments=$true)]
    [string[]]$Args
  )

  Set-StrictMode -Version Latest
  $ErrorActionPreference = 'Stop'

  $script = Join-Path $PSScriptRoot '..\..\..\run_today_and_export.ps1'
  & $script @Args
}