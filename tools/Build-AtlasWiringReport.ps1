[CmdletBinding()]
param(
  [string]$RepoRoot = (Get-Location).Path,
  [string]$OutDir = (Join-Path (Get-Location).Path ".atlas_audit"),
  [string[]]$IgnoreRegex = @('\\.git\\','\\node_modules\\','\\__pycache__\\','\\\.venv\\')
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Ensure-Dir([string]$p){ if(-not(Test-Path $p)){ New-Item -ItemType Directory -Path $p | Out-Null } }

Ensure-Dir $OutDir

$py = Get-ChildItem $RepoRoot -Recurse -File -Filter *.py |
  Where-Object {
    $full = $_.FullName
    foreach($rx in $IgnoreRegex){ if($full -match $rx){ return $false } }
    return $true
  }

$ps = Get-ChildItem $RepoRoot -Recurse -File -Include *.ps1,*.psm1,*.cmd,*.bat |
  Where-Object {
    $full = $_.FullName
    foreach($rx in $IgnoreRegex){ if($full -match $rx){ return $false } }
    return $true
  }

# 1) Python entrypoints
$entrypoints = foreach($f in $py){
  $t = Get-Content $f.FullName -Raw -ErrorAction SilentlyContinue
  if($t -match '__name__\s*==\s*[''"]__main__[''"]'){
    [pscustomobject]@{
      RelPath = $f.FullName.Substring($RepoRoot.Length).TrimStart('\','/')
      HasArgparse = [bool]($t -match '\bargparse\b')
      HasTyper    = [bool]($t -match '\btyper\b')
      HasClick    = [bool]($t -match '\bclick\b')
    }
  }
}

# 2) PowerShell -> Python invocations
$invokes = foreach($f in $ps){
  Select-String -Path $f.FullName -Pattern '\bpython(\.exe)?\b|\bpy(\.exe)?\b' -ErrorAction SilentlyContinue |
    ForEach-Object {
      [pscustomobject]@{
        RelPath = $_.Path.Substring($RepoRoot.Length).TrimStart('\','/')
        LineNumber = $_.LineNumber
        Line = $_.Line.Trim()
      }
    }
}

# 3) Quick python->tools/atlas import hints (lightweight)
$imports = foreach($f in $py){
  $t = Get-Content $f.FullName -Raw -ErrorAction SilentlyContinue
  $rel = $f.FullName.Substring($RepoRoot.Length).TrimStart('\','/')
  $hits = @()
  if($t -match 'from\s+tools\b|import\s+tools\b'){ $hits += "imports tools" }
  if($t -match 'from\s+atlas\b|import\s+atlas\b'){ $hits += "imports atlas" }
  if($hits.Count -gt 0){
    [pscustomobject]@{ RelPath=$rel; Hints=($hits -join ", ") }
  }
}

# Write outputs
$entryCsv = Join-Path $OutDir "wiring_entrypoints.csv"
$invokeCsv = Join-Path $OutDir "wiring_ps_invokes.csv"
$importCsv = Join-Path $OutDir "wiring_import_hints.csv"
$mdPath    = Join-Path $OutDir "WIRING.md"

$entrypoints | Sort-Object RelPath | Export-Csv -NoTypeInformation -Path $entryCsv
$invokes     | Sort-Object RelPath,LineNumber | Export-Csv -NoTypeInformation -Path $invokeCsv
$imports     | Sort-Object RelPath | Export-Csv -NoTypeInformation -Path $importCsv

$md = New-Object System.Collections.Generic.List[string]
$md.Add("# Atlas wiring report") | Out-Null
$md.Add("") | Out-Null
$md.Add("Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')") | Out-Null
$md.Add("") | Out-Null

$md.Add("## Python entrypoints (__main__)") | Out-Null
$md.Add("") | Out-Null
foreach($e in ($entrypoints | Sort-Object RelPath)){
  $md.Add("- `$($e.RelPath)` (argparse=$($e.HasArgparse), typer=$($e.HasTyper), click=$($e.HasClick))") | Out-Null
}
if(-not $entrypoints){ $md.Add("- (none found)") | Out-Null }
$md.Add("") | Out-Null

$md.Add("## PowerShell/batch invoking python") | Out-Null
$md.Add("") | Out-Null
foreach($i in ($invokes | Sort-Object RelPath,LineNumber)){
  $md.Add("- `$($i.RelPath):$($i.LineNumber)`  `"$($i.Line)`"") | Out-Null
}
if(-not $invokes){ $md.Add("- (none found)") | Out-Null }
$md.Add("") | Out-Null

$md.Add("## Import hints (who imports tools/atlas)") | Out-Null
$md.Add("") | Out-Null
foreach($h in ($imports | Sort-Object RelPath)){
  $md.Add("- `$($h.RelPath)` — $($h.Hints)") | Out-Null
}
if(-not $imports){ $md.Add("- (none found)") | Out-Null }

Set-Content -LiteralPath $mdPath -Value ($md -join "`n") -Encoding UTF8

Write-Host "Wrote wiring report:" -ForegroundColor Green
Write-Host "  $mdPath"
Write-Host "  $entryCsv"
Write-Host "  $invokeCsv"
Write-Host "  $importCsv"