[CmdletBinding(SupportsShouldProcess)]
param(
  [string]$RepoRoot = (Get-Location).Path
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Normalize-Path([string]$p) { [IO.Path]::GetFullPath($p) }

function Move-IfExists {
  param(
    [Parameter(Mandatory)][string]$Source,
    [Parameter(Mandatory)][string]$DestinationDir
  )

  if (-not (Test-Path -LiteralPath $Source)) { return }

  if (-not (Test-Path -LiteralPath $DestinationDir)) {
    New-Item -ItemType Directory -Path $DestinationDir -Force | Out-Null
  }

  $fileName = [IO.Path]::GetFileName($Source)
  $dest = Join-Path $DestinationDir $fileName

  if ($PSCmdlet.ShouldProcess($Source, "Move to $dest")) {
    Move-Item -LiteralPath $Source -Destination $dest -Force
  }
}

$repo = Normalize-Path $RepoRoot
$devRoot = Join-Path $repo "scripts\dev"
$quarantineRoot = Join-Path $devRoot "tools_quarantine"

if (-not (Test-Path -LiteralPath $devRoot)) {
  throw "scripts/dev not found."
}

# ---- BOARDS ----
$boards = @(
  "snapshot_prizepicks_board.py",
  "update_board_from_prizepicks.py",
  "compare_snapshots.py",
  "build_audit_last5_board.py"
)

foreach ($f in $boards) {
  Move-IfExists (Join-Path $devRoot $f) (Join-Path $devRoot "boards")
}

# ---- GAMELOGS ----
$gamelogs = @(
  "update_gamelogs.py",
  "update_all_gamelogs.py"
)

foreach ($f in $gamelogs) {
  Move-IfExists (Join-Path $devRoot $f) (Join-Path $devRoot "gamelogs")
}

# refresh_nba_gamelogs.py (currently in quarantine)
Move-IfExists (Join-Path $quarantineRoot "refresh_nba_gamelogs.py") (Join-Path $devRoot "gamelogs")

# ---- VALIDATION ----
$validation = @(
  "validate_recs_vs_today.py",
  "enforce_playability_on_today.py",
  "test_playability.py"
)

foreach ($f in $validation) {
  Move-IfExists (Join-Path $devRoot $f) (Join-Path $devRoot "validation")
}

# ---- ANALYSIS ----
$analysis = @(
  "graph_and_testbet_730.py",
  "top3_parlays_from_compare.py"
)

foreach ($f in $analysis) {
  Move-IfExists (Join-Path $devRoot $f) (Join-Path $devRoot "analysis")
}

# ---- EXPORT ----
$exportFromQuarantine = @(
  "export_cloudflare_payload.py",
  "export_invalidations_to_dashboard.py",
  "export_recommended_to_dashboard.py",
  "export_status_to_dashboard.py"
)

foreach ($f in $exportFromQuarantine) {
  Move-IfExists (Join-Path $quarantineRoot $f) (Join-Path $devRoot "export")
}

# ---- ADHOC ----
$adhocRoot = Join-Path $devRoot "adhoc"

Move-IfExists (Join-Path $devRoot "build_external_slips_from_picks.py") $adhocRoot
Move-IfExists (Join-Path $devRoot "write_definitions_readme.py") $adhocRoot

$adhocFromQuarantine = @(
  "gamescript_best_combos.py",
  "parse_bettingpros_paste.py",
  "fetch_rotowire_priors.py",
  "finalize_now.py",
  "postprocess_outputs.py",
  "build_roster_and_slate.py"
)

foreach ($f in $adhocFromQuarantine) {
  Move-IfExists (Join-Path $quarantineRoot $f) $adhocRoot
}

# ---- Injury subfolder ----
$injurySrc = Join-Path $quarantineRoot "injury"
$injuryDest = Join-Path $adhocRoot "injury"

if (Test-Path -LiteralPath $injurySrc) {
  if (-not (Test-Path -LiteralPath $injuryDest)) {
    New-Item -ItemType Directory -Path $injuryDest -Force | Out-Null
  }

  Get-ChildItem -LiteralPath $injurySrc -File | ForEach-Object {
    $dest = Join-Path $injuryDest $_.Name
    if ($PSCmdlet.ShouldProcess($_.FullName, "Move to $dest")) {
      Move-Item -LiteralPath $_.FullName -Destination $dest -Force
    }
  }
}

Write-Host "Dev scripts organized." -ForegroundColor Green