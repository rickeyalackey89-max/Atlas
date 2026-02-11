Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$private = Join-Path $PSScriptRoot 'Private'
if (Test-Path -LiteralPath $private) {
  Get-ChildItem -LiteralPath $private -Filter '*.ps1' -File -Recurse | ForEach-Object { . $_.FullName }
}

$public = Join-Path $PSScriptRoot 'Public'
if (Test-Path -LiteralPath $public) {
  Get-ChildItem -LiteralPath $public -Filter '*.ps1' -File -Recurse | ForEach-Object { . $_.FullName }
}

# Export everything in Public (manifest can also control this)
Export-ModuleMember -Function (Get-ChildItem -LiteralPath $public -Filter '*.ps1' -File | Select-Object -ExpandProperty BaseName)