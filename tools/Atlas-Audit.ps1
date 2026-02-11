#requires -Version 5.1
[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)]
  [string]$RepoRoot,

  [string]$OutDir = (Join-Path -Path (Get-Location) -ChildPath ("atlas_audit_" + (Get-Date -Format "yyyyMMdd_HHmmss"))),

  [switch]$IncludeContentSnippets,

  [ValidateRange(256,200000)]
  [int]$SnippetChars = 4000
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function New-Dir([string]$Path) {
  if (-not (Test-Path -LiteralPath $Path)) { New-Item -ItemType Directory -Path $Path | Out-Null }
}

function Get-Rel([string]$Root, [string]$Full) {
  $r = $Root.TrimEnd('\','/')
  if ($Full.Length -lt $r.Length) { return $Full }
  $Full.Substring($r.Length).TrimStart('\','/')
}

function Safe-ReadAllText([string]$Path) {
  try { Get-Content -LiteralPath $Path -Raw -ErrorAction Stop } catch { $null }
}

function Snip([string]$Text, [int]$MaxChars) {
  if ($null -eq $Text) { return $null }
  if ($Text.Length -le $MaxChars) { return $Text }
  $Text.Substring(0,$MaxChars) + "`n...<truncated>..."
}

$root = (Resolve-Path -LiteralPath $RepoRoot).Path

New-Dir $OutDir
$invDir = Join-Path $OutDir "inventory"
$ciDir  = Join-Path $OutDir "ci"
$psDir  = Join-Path $OutDir "ps"
$cfDir  = Join-Path $OutDir "cloudflare"
New-Dir $invDir; New-Dir $ciDir; New-Dir $psDir; New-Dir $cfDir

# --- Files (exclude .git)
$allFiles = Get-ChildItem -LiteralPath $root -Recurse -File -Force |
  Where-Object { $_.FullName -notmatch '\\\.git\\' -and $_.Name -ne '.DS_Store' }

# --- Inventory
$inventory = foreach ($f in $allFiles) {
  $hash = $null
  try { $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $f.FullName).Hash } catch { }
  [pscustomobject]@{
    RelativePath = (Get-Rel $root $f.FullName)
    Extension    = $f.Extension
    SizeBytes    = [int64]$f.Length
    LastWriteUtc = $f.LastWriteTimeUtc
    SHA256       = $hash
  }
}

$inventory | Sort-Object Extension, RelativePath |
  Export-Csv -NoTypeInformation -LiteralPath (Join-Path $invDir "file_inventory.csv")
$inventory | ConvertTo-Json -Depth 6 |
  Set-Content -Encoding UTF8 -LiteralPath (Join-Path $invDir "file_inventory.json")

# --- CI workflows copy
$workflowDir = Join-Path $root ".github\workflows"
$workflowFiles = @()
if (Test-Path -LiteralPath $workflowDir) {
  $workflowFiles = Get-ChildItem -LiteralPath $workflowDir -File -Recurse -ErrorAction SilentlyContinue
  foreach ($wf in $workflowFiles) {
    Copy-Item -LiteralPath $wf.FullName -Destination (Join-Path $ciDir $wf.Name) -Force
    if ($IncludeContentSnippets) {
      $txt = Safe-ReadAllText $wf.FullName
      (Snip $txt $SnippetChars) | Set-Content -Encoding UTF8 -LiteralPath (Join-Path $ciDir ($wf.Name + ".snippet.txt"))
    }
  }
}

# --- Cloudflare/JS configs copy
$cfCandidates = @("wrangler.toml","wrangler.json","package.json","pnpm-lock.yaml","yarn.lock","package-lock.json","npm-shrinkwrap.json")
foreach ($name in $cfCandidates) {
  $p = Join-Path $root $name
  if (Test-Path -LiteralPath $p) {
    Copy-Item -LiteralPath $p -Destination (Join-Path $cfDir $name) -Force
    if ($IncludeContentSnippets) {
      $txt = Safe-ReadAllText $p
      (Snip $txt $SnippetChars) | Set-Content -Encoding UTF8 -LiteralPath (Join-Path $cfDir ($name + ".snippet.txt"))
    }
  }
}

# --- PowerShell AST analysis
Add-Type -AssemblyName System.Management.Automation
$psFiles = $allFiles | Where-Object { $_.Extension -in ".ps1",".psm1",".psd1" }

$functionIndex = @()
$depHints = @()

foreach ($f in $psFiles) {
  $tokens = $null; $errors = $null
  $ast = [System.Management.Automation.Language.Parser]::ParseFile($f.FullName, [ref]$tokens, [ref]$errors)

  foreach ($err in @($errors)) {
    $depHints += [pscustomobject]@{
      File = (Get-Rel $root $f.FullName)
      Kind = "ParseError"
      Line = $err.Extent.StartLineNumber
      Text = $err.Message
    }
  }

  $funcs = $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $true)
  foreach ($fn in @($funcs)) {
    $functionIndex += [pscustomobject]@{
      File = (Get-Rel $root $f.FullName)
      Function = $fn.Name
      StartLine = $fn.Extent.StartLineNumber
      EndLine = $fn.Extent.EndLineNumber
      IsWorkflow = $fn.IsWorkflow
    }
  }

  $cmds = $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.CommandAst] }, $true)
  foreach ($cmd in @($cmds)) {
    $t = $cmd.Extent.Text.Trim()

    if ($t -match '^\.\s+["'']?(\.\\|\.\.\\)') { $depHints += [pscustomobject]@{ File=(Get-Rel $root $f.FullName); Kind="DotSourcing";  Line=$cmd.Extent.StartLineNumber; Text=$t } }
    if ($t -match '^\s*(Import-Module|using\s+module)\b') { $depHints += [pscustomobject]@{ File=(Get-Rel $root $f.FullName); Kind="ModuleImport"; Line=$cmd.Extent.StartLineNumber; Text=$t } }
    if ($t -match '\b(Invoke-RestMethod|Invoke-WebRequest|System\.Net\.Http|New-Object\s+Net\.WebClient)\b') { $depHints += [pscustomobject]@{ File=(Get-Rel $root $f.FullName); Kind="NetworkIO";    Line=$cmd.Extent.StartLineNumber; Text=$t } }
    if ($t -match '\b(Get-Content|Set-Content|Add-Content|Out-File|Export-Csv|Import-Csv|ConvertTo-Json|ConvertFrom-Json)\b') { $depHints += [pscustomobject]@{ File=(Get-Rel $root $f.FullName); Kind="FileIO";       Line=$cmd.Extent.StartLineNumber; Text=$t } }
    if ($t -match '\b(Start-Process)\b' -or $t -match '(^|[^A-Za-z0-9_])&\s+\S+(\.exe|\.cmd|\.bat)\b') { $depHints += [pscustomobject]@{ File=(Get-Rel $root $f.FullName); Kind="ProcessExec"; Line=$cmd.Extent.StartLineNumber; Text=$t } }
  }
}

$functionIndex | Sort-Object Function, File |
  Export-Csv -NoTypeInformation -LiteralPath (Join-Path $psDir "function_index.csv")
$depHints | Sort-Object Kind, File, Line |
  Export-Csv -NoTypeInformation -LiteralPath (Join-Path $psDir "dependency_hints.csv")

# --- Cloudflare detection
$cf = [ordered]@{
  RepoRoot = $root
  HasWorkflows = [bool](Test-Path -LiteralPath $workflowDir)
  WorkflowFiles = @($workflowFiles | ForEach-Object Name)
  HasWranglerToml = [bool](Test-Path -LiteralPath (Join-Path $root "wrangler.toml"))
  HasWranglerJson = [bool](Test-Path -LiteralPath (Join-Path $root "wrangler.json"))
  HasPackageJson  = [bool](Test-Path -LiteralPath (Join-Path $root "package.json"))
  Notes = @()
}

foreach ($wf in @($workflowFiles)) {
  $yml = Safe-ReadAllText $wf.FullName
  if ($null -eq $yml) { continue }
  if ($yml -match '(?i)\bwrangler\b') { $cf.Notes += "Workflow references wrangler ($($wf.Name))" }
  if ($yml -match '(?i)cloudflare/pages|pages deploy|\bpages\b') { $cf.Notes += "Workflow appears to deploy Pages ($($wf.Name))" }
  if ($yml -match '(?i)\bworkers\b') { $cf.Notes += "Workflow references Workers ($($wf.Name))" }
  if ($yml -match '(?i)\bR2\b|\bKV\b|\bD1\b') { $cf.Notes += "Workflow references R2/KV/D1 ($($wf.Name))" }
}

$cf | ConvertTo-Json -Depth 6 |
  Set-Content -Encoding UTF8 -LiteralPath (Join-Path $cfDir "cloudflare_detection.json")

# --- Summary
$summary = [ordered]@{
  RepoRoot        = $root
  OutDir          = (Resolve-Path -LiteralPath $OutDir).Path
  TotalFiles      = @($allFiles).Count
  PowerShellFiles = @($psFiles).Count
  FunctionCount   = @($functionIndex).Count
  ParseErrors     = @($depHints | Where-Object Kind -eq "ParseError").Count
  DotSourcing     = @($depHints | Where-Object Kind -eq "DotSourcing").Count
  ModuleImports   = @($depHints | Where-Object Kind -eq "ModuleImport").Count
  NetworkIO       = @($depHints | Where-Object Kind -eq "NetworkIO").Count
  FileIO          = @($depHints | Where-Object Kind -eq "FileIO").Count
  ProcessExec     = @($depHints | Where-Object Kind -eq "ProcessExec").Count
  WorkflowCount   = @($workflowFiles).Count
}

$summary | ConvertTo-Json -Depth 6 |
  Set-Content -Encoding UTF8 -LiteralPath (Join-Path $OutDir "audit_summary.json")

($summary.GetEnumerator() | Sort-Object Name | ForEach-Object { "{0}: {1}" -f $_.Name, $_.Value }) |
  Set-Content -Encoding UTF8 -LiteralPath (Join-Path $OutDir "audit_summary.txt")

Write-Host "✅ Atlas audit bundle created at: $($summary.OutDir)" -ForegroundColor Green
Write-Host "Key outputs:" -ForegroundColor Cyan
Write-Host "  inventory\file_inventory.csv"
Write-Host "  ci\ (workflows copied here if present)"
Write-Host "  ps\function_index.csv"
Write-Host "  ps\dependency_hints.csv"
Write-Host "  cloudflare\cloudflare_detection.json"
Write-Host "  audit_summary.txt"
