#requires -Version 5.1
[CmdletBinding()]
param(
  [Parameter(Mandatory)]
  [string]$TraceLogPath,

  [string]$RepoRoot = (Get-Location).Path,
  [string]$OutDir = ".\.atlas_audit",

  # Include non-repo paths if you want to see them
  [switch]$IncludeNonRepo
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $TraceLogPath)) {
  throw "Trace log not found: $TraceLogPath"
}

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$repoFull = [System.IO.Path]::GetFullPath($RepoRoot)

function ConvertTo-RepoRelativePath([string]$full) {
  $full2 = [System.IO.Path]::GetFullPath($full)
  if ($full2.StartsWith($repoFull, [System.StringComparison]::OrdinalIgnoreCase)) {
    return $full2.Substring($repoFull.Length).TrimStart('\','/')
  }
  return $full2
}

# Lines look like:
# [subprocess.run] ...  ['python.exe', 'C:\...\Atlas\tools\fetch_apis.py', '--raw-only'] kwargs={...}
$lines = Get-Content -LiteralPath $TraceLogPath

$items = New-Object System.Collections.Generic.List[object]

# When parsing argument lists, don't assign to $args (automatic). Example:
foreach ($line in $lines) {
  # ...parse into $procArgs instead of $args...
  $procArgs = @()  # safe local name
  # populate $procArgs from regex/extraction code
  # e.g. $procArgs = $matches['args'].Split(',') ...

  # Extract the Python-style list between first '[' and matching '] kwargs='
  # We'll capture the LAST [...] before "kwargs=" to avoid the prefix bracket.
  $m = [regex]::Match($line, '\]\s+\d{4}.*?\s+(?<list>\[.*\])\s+kwargs=')
  if (-not $m.Success) {
    # os.system format might differ; skip for now
    continue
  }

  $listText = $m.Groups['list'].Value

  # Convert a Python repr list -> JSON-ish -> ConvertFrom-Json
  # This is pragmatic and works for typical simple args
  $jsonish = $listText.Replace("'", '"')

  try {
    $arr = $jsonish | ConvertFrom-Json
  } catch {
    continue
  }

  if (-not $arr -or $arr.Count -lt 2) { continue }

  $exe = [string]$arr[0]
  $scriptOrCmd = [string]$arr[1]
  $procArgs = @()
  if ($arr.Count -gt 2) { $procArgs = @($arr | Select-Object -Skip 2 | ForEach-Object { [string]$_ }) }

  # Only keep .py/.ps1 executed scripts
  if ($scriptOrCmd -notmatch '\.(py|ps1)$') { continue }

  $fullScript = $scriptOrCmd
  if (-not [System.IO.Path]::IsPathRooted($fullScript)) {
    $fullScript = Join-Path $RepoRoot $fullScript
  }
  $fullScript = [System.IO.Path]::GetFullPath($fullScript)

  if (-not $IncludeNonRepo) {
    if (-not $fullScript.StartsWith($repoFull, [System.StringComparison]::OrdinalIgnoreCase)) {
      continue
    }
  }

  $items.Add([pscustomobject]@{
    Executable = $exe
    ScriptFull = $fullScript
    ScriptRel  = (To-RepoRelativeIfPossible $fullScript)
    Args       = $procArgs
    RawLine    = $line
  }) | Out-Null
}

# De-dupe by (ScriptRel + Args string)
$dedup = $items |
  Group-Object { $_.ScriptRel + " || " + ($_.Args -join ' ') } |
  ForEach-Object { $_.Group[0] }

$ts = Get-Date -Format "yyyyMMdd_HHmmss"
$outJson = Join-Path $OutDir "orchestrator_child_exec_$ts.json"
$outTxt  = Join-Path $OutDir "orchestrator_child_exec_$ts.txt"

$dedup | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $outJson -Encoding UTF8

$dedup | ForEach-Object {
  "{0}`t{1}" -f $_.ScriptRel, ($_.Args -join ' ')
} | Set-Content -LiteralPath $outTxt -Encoding UTF8

Write-Host ("Found {0} unique executed child script(s)." -f ($dedup.Count))
Write-Host "Wrote: $outTxt"
Write-Host "Wrote: $outJson"

# Emit json path
$outJson