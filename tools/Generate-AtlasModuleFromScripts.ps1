#requires -Version 5.1
[CmdletBinding()]
param(
  [Parameter(Mandatory)]
  [ValidateScript({ Test-Path $_ -PathType Container })]
  [string]$RepoRoot,

  [string]$ModuleName = "Atlas",

  [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# StrictMode can throw if $args is ever referenced implicitly; initialize it defensively.
if (-not (Test-Path variable:args)) { $args = @() }

function New-Dir([string]$Path) {
  if (-not (Test-Path -LiteralPath $Path)) { New-Item -ItemType Directory -Path $Path | Out-Null }
}

$repo = (Resolve-Path -LiteralPath $RepoRoot).Path
$moduleRoot = Join-Path $repo "src\$ModuleName"
$publicDir  = Join-Path $moduleRoot "Public"
$privateDir = Join-Path $moduleRoot "Private"

if ($Force -and (Test-Path -LiteralPath $moduleRoot)) {
  Remove-Item -LiteralPath $moduleRoot -Recurse -Force
}

New-Dir $moduleRoot
New-Dir $publicDir
New-Dir $privateDir

# Explicit list of entry scripts (what you showed exists)
$entryScriptNames = @(
  "atlas.ps1",
  "live_feed_publish.ps1",
  "run_all_and_publish.ps1",
  "run_today_and_export.ps1"
)

$entryScripts = foreach ($n in $entryScriptNames) {
  $p = Join-Path $repo $n
  if (Test-Path -LiteralPath $p) { Get-Item -LiteralPath $p }
}

if (-not $entryScripts) {
  throw "No entry scripts found at repo root. Expected: $($entryScriptNames -join ', ')"
}

function Get-CommandNameFromScript([string]$Path) {
  $name = [IO.Path]::GetFileNameWithoutExtension($Path).ToLowerInvariant()
  switch ($name) {
    "atlas"               { "Invoke-Atlas" ; break }
    "live_feed_publish"   { "Invoke-AtlasLiveFeedPublish" ; break }
    "run_all_and_publish" { "Invoke-AtlasRunAllAndPublish" ; break }
    "run_today_and_export"{ "Invoke-AtlasRunTodayAndExport" ; break }
    default {
      # Fallback: Invoke-Atlas + PascalCase of filename parts
      $parts = ($name -split '[^a-z0-9]+' | Where-Object { $_ })
      $pascal = ($parts | ForEach-Object { $_.Substring(0,1).ToUpper() + $_.Substring(1) }) -join ''
      "Invoke-Atlas$pascal"
    }
  }
}

$publicFns = @()

foreach ($s in $entryScripts) {
  $cmdName = Get-CommandNameFromScript $s.FullName
  $publicFns += $cmdName

  $rel = $s.FullName.Substring($repo.Length).TrimStart('\','/')

  # IMPORTANT: this is code that will live INSIDE the module; keep it literal
  $wrapper = @"
function $cmdName {
  [CmdletBinding(PositionalBinding = `$false)]
  param(
    [Parameter(ValueFromRemainingArguments = `$true)]
    [string[]]`$Args
  )

  Set-StrictMode -Version Latest
  `$ErrorActionPreference = 'Stop'

  `$script = Join-Path -Path `$PSScriptRoot -ChildPath '..\..\..\$rel'
  if (-not (Test-Path -LiteralPath `$script)) {
    throw "Underlying script not found: `$script"
  }

  & `$script @Args
}
"@

  Set-Content -LiteralPath (Join-Path $publicDir "$cmdName.ps1") -Value $wrapper -Encoding UTF8
}

# Root module
$psm1Path = Join-Path $moduleRoot "$ModuleName.psm1"
$psm1 = @"
Set-StrictMode -Version Latest
`$ErrorActionPreference = 'Stop'

`$private = Join-Path `$PSScriptRoot 'Private'
if (Test-Path -LiteralPath `$private) {
  Get-ChildItem -LiteralPath `$private -Filter '*.ps1' -File -Recurse | ForEach-Object { . `$_.FullName }
}

`$public = Join-Path `$PSScriptRoot 'Public'
if (Test-Path -LiteralPath `$public) {
  Get-ChildItem -LiteralPath `$public -Filter '*.ps1' -File -Recurse | ForEach-Object { . `$_.FullName }
}

Export-ModuleMember -Function @(
$(($publicFns | Sort-Object -Unique | ForEach-Object { "  '$_'" }) -join ",`r`n")
)
"@
Set-Content -LiteralPath $psm1Path -Value $psm1 -Encoding UTF8

# Minimal manifest (no PSData to avoid your earlier manifest problem)
$psd1Path = Join-Path $moduleRoot "$ModuleName.psd1"
$guid = [guid]::NewGuid().Guid
$exportsLiteral = "@(" + (($publicFns | Sort-Object -Unique | ForEach-Object { "'$_'" }) -join ", ") + ")"

@"
@{
  RootModule        = '$ModuleName.psm1'
  ModuleVersion     = '0.1.0'
  GUID              = '$guid'
  Author            = '$env:USERNAME'
  CompanyName       = ''
  Copyright         = ''
  Description       = '$ModuleName PowerShell module (script-wrapped)'
  PowerShellVersion = '5.1'

  FunctionsToExport = $exportsLiteral
  CmdletsToExport   = @()
  VariablesToExport = @()
  AliasesToExport   = @()
  PrivateData       = @{}
}
"@ | Set-Content -LiteralPath $psd1Path -Encoding UTF8

Write-Host "✅ Generated module at: $moduleRoot" -ForegroundColor Green
Write-Host "Exported commands:" -ForegroundColor Cyan
$publicFns | Sort-Object -Unique | ForEach-Object { Write-Host "  $_" }