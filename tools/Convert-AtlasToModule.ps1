#requires -Version 5.1
<#
.SYNOPSIS
  Converts an existing PowerShell script-based project into a proper module scaffold.

.DESCRIPTION
  - Scans .ps1/.psm1 files under RepoRoot (excluding .git, output folders)
  - Extracts function definitions via AST
  - Writes each function into its own file under src/Atlas/Public or src/Atlas/Private
  - Builds Atlas.psm1 and Atlas.psd1
  - Creates a CLI entry script atlas.ps1 that imports the module and calls Invoke-Atlas (if found)

  This is a "mechanical conversion" (wiring + structure). You can then refactor safely.

.PARAMETER RepoRoot
  Root directory of the Atlas repo.

.PARAMETER ModuleName
  Module folder/name (default Atlas).

.PARAMETER OutputRoot
  Where to place module output (default: <RepoRoot>\src\<ModuleName>)

.PARAMETER PublicFunctionRegex
  If provided, functions matching this regex will be treated as Public.
  Otherwise uses a heuristic: Verb-Noun + comment-based help OR names starting with Invoke-/Get-/Set-/New-/Remove-/Test-/Start-/Stop-.

.PARAMETER Force
  Overwrite existing src/Atlas folder if it exists.

.EXAMPLE
  pwsh .\tools\Convert-AtlasToModule.ps1 -RepoRoot $PWD -Force
#>

[CmdletBinding()]
param(
  [Parameter(Mandatory)]
  [ValidateScript({ Test-Path $_ -PathType Container })]
  [string]$RepoRoot,

  [string]$ModuleName = "Atlas",

  [string]$OutputRoot,

  [string]$PublicFunctionRegex,

  [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function New-Dir([string]$Path) {
  if (-not (Test-Path -LiteralPath $Path)) {
    New-Item -ItemType Directory -Path $Path | Out-Null
  }
}

function Remove-DirSafe([string]$Path) {
  if (Test-Path -LiteralPath $Path) {
    Remove-Item -LiteralPath $Path -Recurse -Force
  }
}

function Get-Rel([string]$Root, [string]$Full) {
  $r = (Resolve-Path -LiteralPath $Root).Path.TrimEnd('\','/')
  $f = (Resolve-Path -LiteralPath $Full).Path
  $f.Substring($r.Length).TrimStart('\','/')
}

function Is-VerbNoun([string]$Name) {
  return [bool]($Name -match '^[A-Z][a-zA-Z0-9]*-[A-Z][a-zA-Z0-9]*$')
}

function Has-CommentHelp([System.Management.Automation.Language.FunctionDefinitionAst]$FnAst) {
  # Heuristic: look for <# .SYNOPSIS ... #> immediately preceding function
  $extent = $FnAst.Extent
  $text = $extent.StartScriptPosition.GetFullScript()
  # Try to detect comment-based help near function start by scanning a small window before function keyword
  $startOffset = [Math]::Max(0, $extent.StartOffset - 2000)
  $window = $text.Substring($startOffset, $extent.StartOffset - $startOffset)
  return [bool]($window -match '(?s)<#\s*\.SYNOPSIS.*?#>\s*$')
}

function Guess-IsPublic([string]$FnName, [System.Management.Automation.Language.FunctionDefinitionAst]$FnAst) {
  if ($PublicFunctionRegex) { return [bool]($FnName -match $PublicFunctionRegex) }
  if (-not (Is-VerbNoun $FnName)) { return $false }

  # Prefer functions that look like commands
  if ($FnName -match '^(Invoke|Get|Set|New|Remove|Test|Start|Stop|Enable|Disable|Add|Clear|Convert|Export|Import|Update|Initialize)-') {
    return $true
  }

  # Or has comment-based help
  if (Has-CommentHelp $FnAst) { return $true }

  return $false
}

function Write-FunctionFile {
  param(
    [Parameter(Mandatory)] [string]$Path,
    [Parameter(Mandatory)] [string]$Content
  )
  $dir = Split-Path -Parent $Path
  New-Dir $dir
  # Ensure UTF8 w/o BOM is fine; Windows PS uses BOM sometimes, but pwsh handles both.
  Set-Content -LiteralPath $Path -Value $Content -Encoding UTF8
}

# Resolve paths
$repo = (Resolve-Path -LiteralPath $RepoRoot).Path
if (-not $OutputRoot) {
  $OutputRoot = Join-Path $repo ("src\" + $ModuleName)
}
$out = $OutputRoot

if (Test-Path -LiteralPath $out) {
  if (-not $Force) {
    throw "OutputRoot already exists: $out  (use -Force to overwrite)"
  }
  Remove-DirSafe $out
}

# Create module folders
$publicDir  = Join-Path $out "Public"
$privateDir = Join-Path $out "Private"
$classesDir = Join-Path $out "Classes"
New-Dir $publicDir
New-Dir $privateDir
New-Dir $classesDir

# Discover candidate source files
$sourceFiles = Get-ChildItem -LiteralPath $repo -Recurse -File -Force |
  Where-Object {
  $_.Extension -in ".ps1",".psm1" -and
  $_.FullName -notmatch '\\\.git\\' -and
  $_.FullName -notmatch '\\src\\' -and
  $_.FullName -notmatch '\\tools\\' -and
  $_.FullName -notmatch '\\\.github\\' -and
  $_.FullName -notmatch '\\ci\\' -and
  $_.FullName -notmatch '\\atlas_audit_' -and
  $_.FullName -notmatch '\\node_modules\\'-and
  $_.FullName -notmatch '\\tools\\' -and
  $_.FullName -notmatch '\\\.github\\' -and
  $_.FullName -notmatch '\\ci\\' -and
  $_.FullName -notmatch '\\atlas_audit_'-and
  $_.FullName -notmatch '\\src\\Atlas\\'
}

if (-not $sourceFiles) {
  throw "No .ps1/.psm1 files found under $repo"
}

Add-Type -AssemblyName System.Management.Automation

$allFunctions = @()

foreach ($f in $sourceFiles) {
  $tokens = $null
  $errors = $null
  $ast = [System.Management.Automation.Language.Parser]::ParseFile($f.FullName, [ref]$tokens, [ref]$errors)

  foreach ($e in @($errors)) {
    Write-Warning ("Parse error in {0}:{1} {2}" -f (Get-Rel $repo $f.FullName), $e.Extent.StartLineNumber, $e.Message)
  }

  $funcAsts = $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $true)

  foreach ($fn in @($funcAsts)) {
    $allFunctions += [pscustomobject]@{
      Name = $fn.Name
      File = $f.FullName
      RelFile = Get-Rel $repo $f.FullName
      StartLine = $fn.Extent.StartLineNumber
      EndLine = $fn.Extent.EndLineNumber
      Text = $fn.Extent.Text
      IsPublic = (Guess-IsPublic -FnName $fn.Name -FnAst $fn)
    }
  }
}

if (-not $allFunctions) {
  throw "No functions found in scanned files."
}

# Deduplicate by Name (keep first occurrence, warn on duplicates)
$dupes = $allFunctions | Group-Object Name | Where-Object Count -gt 1
foreach ($d in $dupes) {
  Write-Warning ("Duplicate function name '{0}' appears {1} times. Keeping first, writing the rest as *-DUPLICATE*.ps1" -f $d.Name, $d.Count)
}

# Write functions into files
$exported = @()
foreach ($grp in ($allFunctions | Group-Object Name)) {
  $items = @($grp.Group)
  $primary = $items[0]

  $isPublic = [bool]$primary.IsPublic
  $targetDir = if ($isPublic) { $publicDir } else { $privateDir }
  $path = Join-Path $targetDir ($primary.Name + ".ps1")

  # Add file header provenance comment
  $header = @(
    "# Generated by Convert-AtlasToModule.ps1"
    ("# Source: {0}:{1}-{2}" -f $primary.RelFile, $primary.StartLine, $primary.EndLine)
    ""
  ) -join "`r`n"

  Write-FunctionFile -Path $path -Content ($header + $primary.Text + "`r`n")

  if ($isPublic) { $exported += $primary.Name }

  # Write duplicates, if any
  if ($items.Count -gt 1) {
    for ($i=1; $i -lt $items.Count; $i++) {
      $dup = $items[$i]
      $dupDir = Join-Path $privateDir "_Duplicates"
      New-Dir $dupDir
      $dupPath = Join-Path $dupDir ("{0}-DUPLICATE-{1}.ps1" -f $dup.Name, $i)
      $dupHeader = @(
        "# Duplicate function definition detected"
        ("# Source: {0}:{1}-{2}" -f $dup.RelFile, $dup.StartLine, $dup.EndLine)
        ""
      ) -join "`r`n"
      Write-FunctionFile -Path $dupPath -Content ($dupHeader + $dup.Text + "`r`n")
    }
  }
}

# Build root module (psm1)
$psm1Path = Join-Path $out ($ModuleName + ".psm1")

$psm1 = @"
Set-StrictMode -Version Latest
`$ErrorActionPreference = 'Stop'

# Load Private functions first
`$private = Join-Path -Path `$PSScriptRoot -ChildPath 'Private'
if (Test-Path -LiteralPath `$private) {
  Get-ChildItem -LiteralPath `$private -Filter '*.ps1' -File -Recurse |
    ForEach-Object { . `$_.FullName }
}

# Load Public functions
`$public = Join-Path -Path `$PSScriptRoot -ChildPath 'Public'
if (Test-Path -LiteralPath `$public) {
  Get-ChildItem -LiteralPath `$public -Filter '*.ps1' -File -Recurse |
    ForEach-Object { . `$_.FullName }
}

# Export only public functions (manifest will also control this)
Export-ModuleMember -Function @(
$(($exported | Sort-Object -Unique | ForEach-Object { "  '$_'" }) -join ",`r`n")
)
"@

Set-Content -LiteralPath $psm1Path -Value $psm1 -Encoding UTF8

# Build module manifest (psd1)
$psd1Path = Join-Path $out ($ModuleName + ".psd1")

# Choose a starter version; you can set this to your app version
$version = [Version]"0.1.0"

# Build a minimal manifest with sane defaults
New-ModuleManifest `
  -Path $psd1Path `
  -RootModule ($ModuleName + ".psm1") `
  -ModuleVersion $version `
  -Guid ([guid]::NewGuid()) `
  -Author $env:USERNAME `
  -CompanyName "" `
  -Copyright "" `
  -Description "$ModuleName - Atlas PowerShell module" `
  -PowerShellVersion "5.1" `
  -FunctionsToExport ($exported | Sort-Object -Unique) `
  -CmdletsToExport @() `
  -AliasesToExport @() `
  -VariablesToExport @() `
  -PrivateData @{
    PSData = @{
      Tags = @("Atlas")
      ProjectUri = ""
      LicenseUri = ""
      ReleaseNotes = "Initial module scaffold generated from existing Atlas scripts."
    }
  } | Out-Null

# Create a CLI entrypoint (atlas.ps1) at repo root if not present
$cliPath = Join-Path $repo "atlas.ps1"
if (-not (Test-Path -LiteralPath $cliPath)) {
  $cli = @"
# Atlas CLI entrypoint
# Usage:
#   pwsh .\atlas.ps1 <args>
param(
  [Parameter(ValueFromRemainingArguments = `$true)]
  [string[]]`$Args
)

`$modulePath = Join-Path -Path `$PSScriptRoot -ChildPath 'src\$ModuleName'
Import-Module `$modulePath -Force

if (Get-Command -Name 'Invoke-Atlas' -ErrorAction SilentlyContinue) {
  Invoke-Atlas @Args
} else {
  Write-Host 'Module imported. Public commands:' -ForegroundColor Cyan
  Get-Command -Module $ModuleName | Sort-Object Name | Format-Table Name, CommandType
  Write-Host ''
  Write-Host 'Tip: create a public function named Invoke-Atlas to make this CLI call it.' -ForegroundColor Yellow
}
"@
  Set-Content -LiteralPath $cliPath -Value $cli -Encoding UTF8
}

Write-Host "✅ Module scaffold created at: $out" -ForegroundColor Green
Write-Host "Exported functions: $(@($exported | Sort-Object -Unique).Count)" -ForegroundColor Cyan
Write-Host "Next: Import-Module `"$out`" -Force; Get-Command -Module $ModuleName" -ForegroundColor Cyan