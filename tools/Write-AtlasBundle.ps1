[CmdletBinding(DefaultParameterSetName="sandbox_engine")]
param(
  # Where to push (folder staging for sandbox consumers)
  [Parameter(Mandatory=$true)]
  [ValidateSet("production","sandbox")]
  [string]$Target,

  # What to bundle into a zip
  [ValidateSet("FULL_RUN","DEAD_PERIOD")]
  [string]$BundleMode = "FULL_RUN",

  [ValidateSet("LIVE","DEAD_PERIOD","IAEL_FAIL","MODEL_FAIL")]
  [string]$GuardrailState = "LIVE",

  # production: typically equals EngineRunId (but keep separate for clarity)
  # sandbox: sandbox run id (sandbox_runs/<RunId>)
  [Parameter(Mandatory=$true)]
  [string]$RunId,

  # Engine run id (runs/<EngineRunId>) - required for FULL_RUN
  [Parameter(Mandatory=$true, ParameterSetName="sandbox_engine")]
  [Parameter(Mandatory=$true, ParameterSetName="production_engine")]
  [string]$EngineRunId,

  # Optional provenance copy (sandbox only). Does NOT affect folder layout.
  [Parameter(ParameterSetName="sandbox_engine")]
  [string]$RawPath,

  [string]$Scenario,
  [string]$RepoRoot = ".",
  [switch]$Strict
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Ensure-Dir([string]$p) {
  if (-not (Test-Path -LiteralPath $p -PathType Container)) {
    New-Item -ItemType Directory -Force -Path $p | Out-Null
  }
}

function Resolve-FileOrNull([string]$p) {
  if (-not $p) { return $null }
  try { return (Resolve-Path -LiteralPath $p).Path } catch { return $null }
}

function Copy-File([string]$src, [string]$dst, [switch]$Required) {
  if (-not $src) {
    if ($Required) { throw "Missing required source path (null)." }
    return $false
  }
  if (Test-Path -LiteralPath $src -PathType Leaf) {
    Ensure-Dir (Split-Path -Path $dst -Parent)
    Copy-Item -LiteralPath $src -Destination $dst -Force
    return $true
  }
  if ($Required) { throw "Missing required file: $src" }
  return $false
}

function Sha256([string]$path) {
  if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { return $null }
  return (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash
}

function Add-IfExistsHash([hashtable]$dst, [string]$key, [string]$path) {
  if (-not $path) { return }
  if (Test-Path -LiteralPath $path -PathType Leaf) {
    $dst[$key] = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash
  }
}

$root = (Resolve-Path -LiteralPath $RepoRoot).Path

# Ensure bundle dirs exist
$bundleRoot  = Join-Path $root "data\bundles"
$stagingRoot = Join-Path $root "data\bundle_staging"
Ensure-Dir $bundleRoot
Ensure-Dir $stagingRoot

$dashDir = Join-Path $root "data\output\dashboard"

$rawFull = Resolve-FileOrNull $RawPath
$rawName = if ($rawFull) { Split-Path -Leaf $rawFull } else { $null }

# Destination "push" directory (existing behavior)
$destDir =
  if ($Target -eq "sandbox") { Join-Path $root "data\output\sandbox_runs\$RunId" }
  else                       { Join-Path $root "data\output\runs\$EngineRunId" }

Ensure-Dir $destDir

Write-Host "============================================="
Write-Host "ATLAS BUNDLE / PUSHER + ZIP"
Write-Host "Target:      $Target"
Write-Host "BundleMode:  $BundleMode"
Write-Host "Guardrail:   $GuardrailState"
Write-Host "RunId:       $RunId"
Write-Host "EngineRunId: $EngineRunId"
if ($Scenario) { Write-Host "Scenario:    $Scenario" }
if ($rawFull)  { Write-Host "Raw:         $rawFull" }
Write-Host "To:          $destDir"
Write-Host "Bundles:     $bundleRoot"
Write-Host "============================================="

# ----------------------------
# DEAD_PERIOD: minimal IAEL zip
# ----------------------------
if ($BundleMode -eq "DEAD_PERIOD") {

  # Push IAEL dashboard pair into dest (optional but convenient)
  Copy-File (Join-Path $dashDir "injury_invalidations_latest.json") (Join-Path $destDir "injury_invalidations_latest.json") -Required:$false | Out-Null
  Copy-File (Join-Path $dashDir "status_latest.json")               (Join-Path $destDir "status_latest.json")               -Required:$false | Out-Null

  $staging = Join-Path $stagingRoot ("{0}__DEAD_PERIOD" -f $RunId)
  if (Test-Path -LiteralPath $staging) { Remove-Item -LiteralPath $staging -Recurse -Force }
  Ensure-Dir $staging

  $iaelOut = Join-Path $staging "iael"
  Ensure-Dir $iaelOut

  $statusSrc = Join-Path $dashDir "status_latest.json"
  $injSrc    = Join-Path $dashDir "injury_invalidations_latest.json"

  Copy-File $statusSrc (Join-Path $iaelOut "status.json") -Required:$true | Out-Null
  Copy-File $injSrc    (Join-Path $iaelOut "injury_invalidations.json") -Required:$true | Out-Null

  $auditOut = Join-Path $staging "audit"
  Ensure-Dir $auditOut
  (@{
    state = "DEAD_PERIOD"
    reason = "IAEL dead period: no live report"
    timestamp_utc = (Get-Date).ToUniversalTime().ToString("o")
  } | ConvertTo-Json -Depth 5) | Set-Content -LiteralPath (Join-Path $auditOut "guardrail_state.json") -Encoding UTF8

  # Clean JSON manifest (no OrderedDictionary Keys/Values wrapper)
  $manifest = [pscustomobject]@{
    bundle_version = "1.1"
    bundle_mode    = "DEAD_PERIOD"
    run_id         = $RunId
    created_utc    = (Get-Date).ToUniversalTime().ToString("o")
    target         = $Target
    guardrail_state= "DEAD_PERIOD"
    iael = @{
      status_sha256 = (Sha256 $statusSrc)
      injury_invalidations_sha256 = (Sha256 $injSrc)
    }
  }

  ($manifest | ConvertTo-Json -Depth 12) | Set-Content -LiteralPath (Join-Path $staging "manifest.json") -Encoding UTF8

  $zipPath = Join-Path $bundleRoot ("atlas_bundle_{0}__DEAD_PERIOD.zip" -f $RunId)
  if (Test-Path -LiteralPath $zipPath) { Remove-Item -LiteralPath $zipPath -Force }
  Compress-Archive -Path (Join-Path $staging "*") -DestinationPath $zipPath -Force

  # Also persist manifest into destDir (so you can see it without unzip)
  Copy-File (Join-Path $staging "manifest.json") (Join-Path $destDir "manifest.json") -Required:$false | Out-Null

  Remove-Item -LiteralPath $staging -Recurse -Force

  Write-Host "✅ DEAD_PERIOD bundle created: $zipPath"
  exit 0
}

# ----------------------------
# FULL_RUN: requires engine dir
# ----------------------------
$engineRunDir = Join-Path $root "data\output\runs\$EngineRunId"
if (-not (Test-Path -LiteralPath $engineRunDir -PathType Container)) {
  throw "Engine run dir not found: $engineRunDir"
}

# Optional raw copy (provenance only)
if ($rawFull -and $Target -eq "sandbox") {
  Copy-File $rawFull (Join-Path $destDir $rawName) -Required:$false | Out-Null
}

# Core outputs (required if -Strict)
Copy-File (Join-Path $engineRunDir "scored_legs.csv")         (Join-Path $destDir "scored_legs.csv")         -Required:$Strict | Out-Null
Copy-File (Join-Path $engineRunDir "scored_legs_deduped.csv") (Join-Path $destDir "scored_legs_deduped.csv") -Required:$Strict | Out-Null

# IAEL dashboard pair (optional, but expected for sandbox consumers)
Copy-File (Join-Path $dashDir "injury_invalidations_latest.json") (Join-Path $destDir "injury_invalidations_latest.json") -Required:$false | Out-Null
Copy-File (Join-Path $dashDir "status_latest.json")               (Join-Path $destDir "status_latest.json")               -Required:$false | Out-Null

# Copy product csvs to top-level (optional)
foreach ($bucket in @("System","Windfall")) {
  $bdir = Join-Path $engineRunDir $bucket
  if (Test-Path -LiteralPath $bdir -PathType Container) {
    Get-ChildItem -LiteralPath $bdir -Filter "recommended_*.csv" -File |
      Sort-Object Name |
      ForEach-Object {
        $dstPath = Join-Path $destDir $_.Name
        if (Test-Path -LiteralPath $dstPath) {
          $dstPath = Join-Path $destDir ("{0}_{1}" -f $bucket, $_.Name)
        }
        Copy-File $_.FullName $dstPath -Required:$false | Out-Null
      }
  }
}

# ----------------------------
# ZIP bundle staging (FULL_RUN)
# ----------------------------
$staging = Join-Path $stagingRoot $EngineRunId
if (Test-Path -LiteralPath $staging) { Remove-Item -LiteralPath $staging -Recurse -Force }
Ensure-Dir $staging

# IAEL
$iaelOut = Join-Path $staging "iael"
Ensure-Dir $iaelOut
Copy-File (Join-Path $dashDir "status_latest.json")               (Join-Path $iaelOut "status.json") -Required:$false | Out-Null
Copy-File (Join-Path $dashDir "injury_invalidations_latest.json") (Join-Path $iaelOut "injury_invalidations.json") -Required:$false | Out-Null

# RAW (if available)
$rawOut = Join-Path $staging "raw"
Ensure-Dir $rawOut
if ($rawFull) {
  Copy-File $rawFull (Join-Path $rawOut $rawName) -Required:$false | Out-Null
}

# BOARD (best-effort)
$boardOut = Join-Path $staging "board"
Ensure-Dir $boardOut
Copy-File (Join-Path $engineRunDir "today.csv") (Join-Path $boardOut "today.csv") -Required:$false | Out-Null
Get-ChildItem -LiteralPath (Join-Path $root "data\board\snapshots") -Filter "board_*.csv" -File -ErrorAction SilentlyContinue |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 1 |
  ForEach-Object { Copy-File $_.FullName (Join-Path $boardOut $_.Name) -Required:$false | Out-Null }

# SCORING
$scoreOut = Join-Path $staging "scoring"
Ensure-Dir $scoreOut
Copy-File (Join-Path $engineRunDir "scored_legs.csv")         (Join-Path $scoreOut "scored_legs.csv")         -Required:$false | Out-Null
Copy-File (Join-Path $engineRunDir "scored_legs_deduped.csv") (Join-Path $scoreOut "scored_legs_deduped.csv") -Required:$false | Out-Null

# OUTPUTS
$outOut = Join-Path $staging "outputs"
Ensure-Dir $outOut
foreach ($bucket in @("System","Windfall")) {
  $bdir = Join-Path $engineRunDir $bucket
  $bOut = Join-Path $outOut $bucket
  if (Test-Path -LiteralPath $bdir -PathType Container) {
    Ensure-Dir $bOut
    Get-ChildItem -LiteralPath $bdir -Filter "recommended_*.csv" -File |
      ForEach-Object {
        Copy-File $_.FullName (Join-Path $bOut $_.Name) -Required:$false | Out-Null
      }
  }
}

# AUDIT
$auditOut = Join-Path $staging "audit"
Ensure-Dir $auditOut
(@{
  state = $GuardrailState
  timestamp_utc = (Get-Date).ToUniversalTime().ToString("o")
} | ConvertTo-Json -Depth 5) | Set-Content -LiteralPath (Join-Path $auditOut "guardrail_state.json") -Encoding UTF8

# Try to include latest PS audit logs if present (best-effort)
$auditDir = Join-Path $root ".atlas_audit"
if (Test-Path -LiteralPath $auditDir -PathType Container) {
  Get-ChildItem -LiteralPath $auditDir -Filter "runlog_${EngineRunId}*.txt" -File -ErrorAction SilentlyContinue |
    Select-Object -First 1 | ForEach-Object { Copy-File $_.FullName (Join-Path $auditOut $_.Name) -Required:$false | Out-Null }
  Get-ChildItem -LiteralPath $auditDir -Filter "events_ps_${EngineRunId}*.jsonl" -File -ErrorAction SilentlyContinue |
    Select-Object -First 1 | ForEach-Object { Copy-File $_.FullName (Join-Path $auditOut $_.Name) -Required:$false | Out-Null }
}

# ----------------------------
# MANIFEST (FULL_RUN) — hardened provenance (v1.1) — clean JSON
# ----------------------------

# Code fingerprints (lightweight)
$codeHashes = @{}
Add-IfExistsHash $codeHashes "run.ps1"               (Join-Path $root "run.ps1")
Add-IfExistsHash $codeHashes "Write-AtlasBundle.ps1" $MyInvocation.MyCommand.Path
Add-IfExistsHash $codeHashes "run_today.py"          (Join-Path $root "run_today.py")

# Identify staged raw and board snapshot
$boardSnapshot = Get-ChildItem -LiteralPath $boardOut -File -Filter "board_*.csv" -ErrorAction SilentlyContinue |
  Sort-Object LastWriteTime -Descending | Select-Object -First 1

$stagedRaw = $null
if ($rawFull -and $rawName) {
  $candidate = Join-Path $rawOut $rawName
  if (Test-Path -LiteralPath $candidate -PathType Leaf) { $stagedRaw = $candidate }
}

# Build manifest as PSCustomObject to guarantee clean JSON object shape
$manifest = [pscustomobject]@{
  bundle_version = "1.1"
  bundle_mode    = "FULL_RUN"
  created_utc    = (Get-Date).ToUniversalTime().ToString("o")

  target         = $Target
  run_id         = $RunId
  engine_run_id  = $EngineRunId
  scenario       = $Scenario
  guardrail_state= $GuardrailState

  replay = @{
    is_replay    = ($Target -eq "sandbox")
    raw_provided = [bool]$rawFull
  }

  inputs = @{
    raw = if ($stagedRaw) {
      @{
        name   = (Split-Path -Leaf $stagedRaw)
        sha256 = (Get-FileHash -LiteralPath $stagedRaw -Algorithm SHA256).Hash
      }
    } else { $null }

    board_snapshot = if ($boardSnapshot) {
      @{
        name   = $boardSnapshot.Name
        sha256 = (Get-FileHash -LiteralPath $boardSnapshot.FullName -Algorithm SHA256).Hash
      }
    } else { $null }

    today_csv = if (Test-Path -LiteralPath (Join-Path $boardOut "today.csv") -PathType Leaf) {
      @{
        name   = "today.csv"
        sha256 = (Get-FileHash -LiteralPath (Join-Path $boardOut "today.csv") -Algorithm SHA256).Hash
      }
    } else { $null }
  }

  environment = @{
    powershell_version = $PSVersionTable.PSVersion.ToString()
    os                 = (Get-CimInstance Win32_OperatingSystem).Caption
    machine            = $env:COMPUTERNAME
    user               = $env:USERNAME
  }

  code = @{
    entry_hint = "run.ps1 → run_today.py → Write-AtlasBundle.ps1"
    hashes     = $codeHashes
  }

  staged_hashes = @{}
}

# Hash all staged files (relative path keys)
Get-ChildItem -LiteralPath $staging -File -Recurse | ForEach-Object {
  $rel = $_.FullName.Substring($staging.Length).TrimStart('\','/')
  $manifest.staged_hashes[$rel] = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
}

# Write manifest into staging
($manifest | ConvertTo-Json -Depth 30) |
  Set-Content -LiteralPath (Join-Path $staging "manifest.json") -Encoding UTF8

# ----------------------------
# ZIP (FULL_RUN) + persist manifest into destDir
# ----------------------------
$zipPath = Join-Path $bundleRoot ("atlas_bundle_{0}.zip" -f $EngineRunId)
if (Test-Path -LiteralPath $zipPath) { Remove-Item -LiteralPath $zipPath -Force }

Compress-Archive -Path (Join-Path $staging "*") -DestinationPath $zipPath -Force

# Persist manifest to dest_dir for convenience (no unzip needed)
Copy-File (Join-Path $staging "manifest.json") (Join-Path $destDir "manifest.json") -Required:$false | Out-Null

# Now safe to remove staging
Remove-Item -LiteralPath $staging -Recurse -Force

# ----------------------------
# Write report (existing behavior)
# ----------------------------
$reportName = if ($Target -eq "sandbox") { "sandbox_report.json" } else { "run_report.json" }

$report = [pscustomobject]@{
  schema        = if ($Target -eq "sandbox") { "atlas.sandbox_bundle.v1" } else { "atlas.run_bundle.v1" }
  created_utc   = (Get-Date).ToUniversalTime().ToString("o")
  target        = $Target
  bundle_mode   = $BundleMode
  guardrail     = $GuardrailState
  run_id        = $RunId
  engine_run_id = $EngineRunId
  scenario      = $Scenario
  raw_path      = $rawFull
  from_dir      = $engineRunDir
  dest_dir      = $destDir
  bundle_zip    = $zipPath
  files         = @()
}

Get-ChildItem -LiteralPath $destDir -File | Sort-Object Name | ForEach-Object {
  $h = Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256
  $report.files += @{
    name   = $_.Name
    bytes  = $_.Length
    sha256 = $h.Hash
  }
}

($report | ConvertTo-Json -Depth 12) | Set-Content -LiteralPath (Join-Path $destDir $reportName) -Encoding UTF8

Write-Host "✅ Bundle complete."
Write-Host "✅ FULL_RUN zip created: $zipPath"
exit 0