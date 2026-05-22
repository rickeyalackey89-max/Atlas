param(
    [string]$CorpusDir = "data\mlb\replay_runs\corpus_replay_20260426_20260519_matchup_source_v2",
    [string]$OutputDir = "data\mlb\model\cat_probability_kernel_v7_24date_exact_winner_neighbors",
    [string]$Version = "mlb_cat_over_residual_v7_24date_exact_winner_neighbors"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $repoRoot

Write-Host "=== MLB targeted replay + CAT LODO job started ==="
Write-Host "repo: $repoRoot"

Write-Host "Step 1/4: Fetching StatsAPI boxscores for 2026-04-26 through 2026-05-19"
uv run atlas-mlb fetch statsapi-boxscores-bulk --start-date 2026-04-26 --end-date 2026-05-19 --json
if ($LASTEXITCODE -ne 0) {
    throw "StatsAPI boxscore backfill failed"
}

Write-Host "Step 2/4: Refreshing season gamelog store through 2026-05-19"
$seasonRefresh = @'
from pathlib import Path
from mlb.runtime.season_gamelogs import refresh_season_gamelogs
import json

manifest = refresh_season_gamelogs(season=2026, through_date="2026-05-19", root=Path("."))
print(json.dumps(manifest, indent=2))
'@
$seasonRefresh | uv run python -
if ($LASTEXITCODE -ne 0) {
    throw "Season gamelog refresh failed"
}

Write-Host "Step 3/4: Running 24-date fidelity replay corpus with DK as-of guard"
.\scripts\mlb\run_fidelity_replay_sweep.ps1 `
    -OutputDir $CorpusDir `
    -RunIdSuffix "matchup_source_v2"
if ($LASTEXITCODE -ne 0) {
    throw "Replay corpus failed"
}

Write-Host "Step 4/4: Running exact mini-grid CAT LODO: winner + two closest misses"
.\scripts\mlb\run_cat_lodo_with_tail.ps1 `
    -CorpusDir $CorpusDir `
    -OutputDir $OutputDir `
    -Version $Version `
    -ModelConfigs "600:0.03:4,400:0.03:4,200:0.06:4" `
    -ResidualScales "0.5,0.65,0.8" `
    -NoTailWindow
if ($LASTEXITCODE -ne 0) {
    throw "CAT LODO failed"
}

Write-Host "=== MLB targeted replay + CAT LODO job complete ==="
