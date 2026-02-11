[CmdletBinding()]
param(
  [Parameter()]
  [ValidateNotNullOrEmpty()]
  [string]$RepoRoot = (Get-Location).Path,

  [Parameter()]
  [ValidateNotNullOrEmpty()]
  [string]$Runner = "run_today.py",

  [Parameter()]
  [ValidateNotNullOrEmpty()]
  [string]$ReportDir = ".atlas_audit",

  [Parameter()]
  [switch]$IncludeToolsInventory,

  # Hard-gate: fail if run_today.py references tools that do not exist
  [Parameter()]
  [switch]$FailOnMissingEntrypoints,

  # Hard-gate (requires -IncludeToolsInventory): fail if any tools/*.py exist but are not wired by run_today.py
  [Parameter()]
  [switch]$FailOnUnwiredTools,

  # Optional allowlist when using -FailOnUnwiredTools (regex applied to RelPath, ex: '^tools/__init__\.py$')
  # Safe with empty arrays (allowed).
  [Parameter()]
  [AllowEmptyCollection()]
  [string[]]$AllowUnwiredToolsRegex = @()
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Ensure-Dir {
  [CmdletBinding()]
  param([Parameter(Mandatory)][ValidateNotNullOrEmpty()][string]$Path)

  if (-not (Test-Path -LiteralPath $Path)) {
    New-Item -ItemType Directory -Path $Path -Force | Out-Null
  }
}

function Normalize-Path {
  [CmdletBinding()]
  param([Parameter(Mandatory)][ValidateNotNullOrEmpty()][string]$Path)

  # Resolve-Path throws if it doesn't exist; GetFullPath normalizes safely
  return [System.IO.Path]::GetFullPath($Path)
}

function Get-RelativePath {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][ValidateNotNullOrEmpty()][string]$BasePath,
    [Parameter(Mandatory)][ValidateNotNullOrEmpty()][string]$FullPath
  )

  $base = (Normalize-Path $BasePath).TrimEnd('\','/')
  $full = (Normalize-Path $FullPath)

  if ($full.Length -lt $base.Length) { return $full }

  if ($full.Substring(0, $base.Length).Equals($base, [System.StringComparison]::OrdinalIgnoreCase)) {
    return $full.Substring($base.Length).TrimStart('\','/')
  }

  return $full
}

function Get-PythonLauncher {
  [CmdletBinding()]
  param()

  $py = Get-Command py -ErrorAction SilentlyContinue
  if ($py) { return $py.Source }

  $python = Get-Command python -ErrorAction SilentlyContinue
  if ($python) { return $python.Source }

  throw "No Python launcher found. Install Python or ensure 'py' or 'python' is on PATH."
}

function Get-PyImportsAst {
  [CmdletBinding()]
  param([Parameter(Mandatory)][ValidateNotNullOrEmpty()][string]$File)

  $launcher = Get-PythonLauncher

  $code = @'
import ast, pathlib
p = pathlib.Path(r"{0}")
t = p.read_text(encoding="utf-8")
m = ast.parse(t)
imps = []
for n in ast.walk(m):
    if isinstance(n, ast.Import):
        for a in n.names:
            imps.append(a.name)
    elif isinstance(n, ast.ImportFrom):
        for a in n.names:
            imps.append(((n.module or "") + "." + a.name).strip("."))
print("\n".join(sorted(set(imps))))
'@ -f $File

  $out = & $launcher -c $code 2>$null
  if ($LASTEXITCODE -ne 0) { return @() }

  return @(
    $out -split "(`r`n|`n|`r)" |
      ForEach-Object { $_.Trim() } |
      Where-Object { $_ }
  )
}

function Get-TextHits {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][ValidateNotNullOrEmpty()][string]$File,
    [Parameter(Mandatory)][ValidateNotNullOrEmpty()][string]$Pattern
  )

  return @(
    Select-String -LiteralPath $File -Pattern $Pattern -AllMatches -ErrorAction SilentlyContinue |
      ForEach-Object { "{0}:{1} {2}" -f $_.Path, $_.LineNumber, $_.Line.Trim() }
  )
}

function Test-IsAllowlistedRelPath {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][ValidateNotNullOrEmpty()][string]$RelPath,
    [Parameter()]
    [AllowEmptyCollection()]
    [string[]]$AllowRegex = @()
  )

  if ($null -eq $AllowRegex -or $AllowRegex.Count -eq 0) { return $false }

  foreach ($rx in $AllowRegex) {
    if ([string]::IsNullOrWhiteSpace($rx)) { continue }
    if ($RelPath -match $rx) { return $true }
  }
  return $false
}

# --- Resolve repo/runner/tools paths ---
$repo = Normalize-Path $RepoRoot
$runnerPath = Join-Path $repo $Runner
if (-not (Test-Path -LiteralPath $runnerPath)) { throw "Runner not found: $runnerPath" }

$toolsDir = Join-Path $repo "tools"
if (-not (Test-Path -LiteralPath $toolsDir)) { throw "tools/ directory not found: $toolsDir" }

$outDir = Join-Path $repo $ReportDir
Ensure-Dir -Path $outDir

# --- 1) Extract wiring from run_today.py AND orchestrator (if exists) ---

$filesToScan = @($runnerPath)

$orchestratorPath = Join-Path $repo "src\Atlas\runtime\orchestrator.py"
if (Test-Path -LiteralPath $orchestratorPath) {
  $filesToScan += $orchestratorPath
}

$rx = [regex]'["'']([^"'']+\.py)["'']'

$toolEntrypoints = @()

foreach ($file in $filesToScan) {

  $text = Get-Content -LiteralPath $file -Raw

  # 1) Match explicit TOOLS_DIR / "file.py" pattern
  $toolsDirRx = [regex]'TOOLS_DIR\s*/\s*"([^"]+\.py)"'
  foreach ($m in $toolsDirRx.Matches($text)) {
    $toolEntrypoints += $m.Groups[1].Value
  }

  # 2) Match Path(...) / "file.py"
  $pathJoinRx = [regex]'["'']([^"'']+\.py)["'']'
  foreach ($m in $pathJoinRx.Matches($text)) {
    $candidate = $m.Groups[1].Value

    # only accept simple filenames (avoid false positives)
    if ($candidate -notmatch '[\\/]' -and $candidate -like '*.py') {
      $toolEntrypoints += $candidate
    }
  }
}

$toolEntrypoints = $toolEntrypoints | Sort-Object -Unique

# --- 2) Resolve entrypoint files & existence ---
$resolved = @(
  foreach ($t in $toolEntrypoints) {
    $full = Join-Path $toolsDir $t
    [pscustomobject]@{
      Entry    = "tools/$t"
      FullPath = $full
      Exists   = (Test-Path -LiteralPath $full)
    }
  }
)

# --- Enforcement: fail if run_today.py references missing tools ---
if ($FailOnMissingEntrypoints) {
  $missing = @($resolved | Where-Object { -not $_.Exists })
  if ($missing.Count -gt 0) {
    $header = ("Missing wired tool entrypoints referenced by {0}`n" -f $Runner)
    $body   = (($missing | ForEach-Object { " - $($_.Entry) => $($_.FullPath)" }) -join "`n")
    throw ($header + $body)
  }
}

# --- 3) Details per entrypoint ---
$details = @(
  foreach ($r in $resolved) {
    if (-not $r.Exists) {
      [pscustomobject]@{
        Entry            = $r.Entry
        Exists           = $false
        ImportsCount     = 0
        LocalImportLines = ""
        SubprocessLines  = ""
        Imports          = ""
      }
      continue
    }

    $imports = @(Get-PyImportsAst -File $r.FullPath)

    $localPattern = '^\s*(from|import)\s+(Atlas|atlas|tools|src|playability)\b'
    $subPattern   = 'subprocess\.run|check_call|check_output|Popen|os\.system|runpy\.run_path|python\s+.+\.py|\.py"'

    $localHits = @(Get-TextHits -File $r.FullPath -Pattern $localPattern)
    $subHits   = @(Get-TextHits -File $r.FullPath -Pattern $subPattern)

    [pscustomobject]@{
      Entry            = $r.Entry
      Exists           = $true
      ImportsCount     = $imports.Count
      LocalImportLines = ($localHits -join " | ")
      SubprocessLines  = ($subHits -join " | ")
      Imports          = ($imports -join "; ")
    }
  }
)

# --- 4) Optional inventory of tools/*.py not referenced by run_today.py ---
$toolsInventory = @()
$notWired = @()

if ($IncludeToolsInventory) {
  $toolFiles = @(
    Get-ChildItem -LiteralPath $toolsDir -Recurse -File -Filter *.py -ErrorAction SilentlyContinue |
      Where-Object { $_.FullName -notmatch '\\__pycache__\\' }
  )

  # Build normalized wired set (case-insensitive)
  $wiredSet = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)
  foreach ($e in $toolEntrypoints) {
    $wiredFull = Normalize-Path (Join-Path $toolsDir $e)
    [void]$wiredSet.Add($wiredFull)
  }

  $toolsInventory = @(
    foreach ($f in $toolFiles) {
      $fullNorm = Normalize-Path $f.FullName
      $rel      = Get-RelativePath -BasePath $repo -FullPath $fullNorm

      $allowlisted = Test-IsAllowlistedRelPath -RelPath $rel -AllowRegex $AllowUnwiredToolsRegex

      [pscustomobject]@{
        RelPath         = $rel
        FullPath        = $fullNorm
        WiredByRunToday = $wiredSet.Contains($fullNorm)
        Allowlisted     = $allowlisted
      }
    }
  )

  $notWired = @(
    $toolsInventory |
      Where-Object { -not $_.WiredByRunToday -and -not $_.Allowlisted } |
      Sort-Object RelPath
  )

  if ($FailOnUnwiredTools) {
    if ($notWired.Count -gt 0) {
      $header = "Unwired tools detected under tools/ (quarantine these to scripts/dev/tools_quarantine/):`n"
      $body   = (($notWired | ForEach-Object { " - $($_.RelPath)" }) -join "`n")
      throw ($header + $body)
    }
  }
}
elseif ($FailOnUnwiredTools) {
  throw "-FailOnUnwiredTools requires -IncludeToolsInventory (so we actually scan tools/)."
}

# --- 5) Write reports ---
$csv1 = Join-Path $outDir "runtime_wiring_entrypoints.csv"
$csv2 = Join-Path $outDir "runtime_wiring_details.csv"
$md   = Join-Path $outDir "RUNTIME_WIRING.md"

$resolved | Select-Object Entry, Exists, FullPath | Export-Csv -NoTypeInformation -Path $csv1
$details  | Export-Csv -NoTypeInformation -Path $csv2

$lines = New-Object 'System.Collections.Generic.List[string]'
$lines.Add("# Atlas runtime wiring") | Out-Null
$lines.Add("") | Out-Null
$lines.Add("Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')") | Out-Null
$lines.Add("") | Out-Null

$lines.Add(("## Direct entrypoints invoked by {0}" -f $Runner)) | Out-Null
$lines.Add("") | Out-Null
foreach ($r in $resolved) {
  $status = if ($r.Exists) { "OK" } else { "MISSING" }
  $lines.Add("- $($r.Entry) — **$status**") | Out-Null
}
$lines.Add("") | Out-Null

$lines.Add("## Entrypoint details") | Out-Null
$lines.Add("") | Out-Null
foreach ($d in $details) {
  $lines.Add("### $($d.Entry)") | Out-Null
  $lines.Add("") | Out-Null
  $lines.Add("- Exists: $($d.Exists)") | Out-Null
  $lines.Add("- ImportsCount: $($d.ImportsCount)") | Out-Null

  $local = if ([string]::IsNullOrWhiteSpace($d.LocalImportLines)) { "(none)" } else { $d.LocalImportLines }
  $subs  = if ([string]::IsNullOrWhiteSpace($d.SubprocessLines))  { "(none)" } else { $d.SubprocessLines }

  $lines.Add("- LocalImports: $local") | Out-Null
  $lines.Add("- SubprocessMentions: $subs") | Out-Null
  $lines.Add("") | Out-Null
}

if ($IncludeToolsInventory) {
  $lines.Add("## Tools inventory (not referenced by run_today.py)") | Out-Null
  $lines.Add("") | Out-Null
  $lines.Add("Count: $($notWired.Count)") | Out-Null
  $lines.Add("") | Out-Null
  foreach ($x in $notWired) { $lines.Add("- $($x.RelPath)") | Out-Null }

  $invCsv = Join-Path $outDir "tools_inventory.csv"
  $toolsInventory |
    Select-Object RelPath, WiredByRunToday, Allowlisted, FullPath |
    Export-Csv -NoTypeInformation -Path $invCsv
}

Set-Content -LiteralPath $md -Value ($lines -join "`n") -Encoding UTF8

Write-Host "Wrote runtime wiring reports:" -ForegroundColor Green
Write-Host "  $md"
Write-Host "  $csv1"
Write-Host "  $csv2"
if ($IncludeToolsInventory) {
  Write-Host "  $(Join-Path $outDir 'tools_inventory.csv')"
}