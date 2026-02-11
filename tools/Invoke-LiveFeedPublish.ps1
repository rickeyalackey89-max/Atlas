function Invoke-LiveFeedPublish {
  [CmdletBinding(PositionalBinding=$false)]
  param(
    [Parameter(ValueFromRemainingArguments=$true)]
    [string[]]$Args
  )

  Set-StrictMode -Version Latest
  $ErrorActionPreference = 'Stop'

  $script = Join-Path $PSScriptRoot '..\..\..\live_feed_publish.ps1'
  & $script @Args
}