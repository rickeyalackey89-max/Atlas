param(
    [string]$OutputDir = "data\mlb\eval\corpus_replay_20260426_20260520_strict_fidelity_v1",
    [switch]$RefreshBettingProsOdds,
    [string]$CalibrationArtifact = "",
    [string]$RunIdSuffix = "github_csv_fidelity_v1",
    [string[]]$ReplayDates = @(),
    [switch]$SkipPreflight
)

$ErrorActionPreference = "Continue"
$items = @(
    @("2026-04-26", "github_prizepicks_csv_20260426T155759Z"),
    @("2026-04-27", "github_prizepicks_csv_20260427T175625Z"),
    @("2026-04-28", "github_prizepicks_csv_20260428T191202Z"),
    @("2026-04-29", "github_prizepicks_csv_20260429T185745Z"),
    @("2026-04-30", "github_prizepicks_csv_20260430T180044Z"),
    @("2026-05-01", "github_prizepicks_csv_20260501T153456Z"),
    @("2026-05-02", "github_prizepicks_csv_20260502T173243Z"),
    @("2026-05-03", "github_prizepicks_csv_20260503T173440Z"),
    @("2026-05-04", "github_prizepicks_csv_20260504T153332Z"),
    @("2026-05-05", "github_prizepicks_csv_20260505T170747Z"),
    @("2026-05-06", "github_prizepicks_csv_20260506T191318Z"),
    @("2026-05-07", "github_prizepicks_csv_20260507T161935Z"),
    @("2026-05-08", "github_prizepicks_csv_20260508T160234Z"),
    @("2026-05-09", "github_prizepicks_csv_20260509T173823Z"),
    @("2026-05-10", "github_prizepicks_csv_20260510T151655Z"),
    @("2026-05-11", "github_prizepicks_csv_20260511T180328Z"),
    @("2026-05-12", "github_prizepicks_csv_20260512T163914Z"),
    @("2026-05-13", "github_prizepicks_csv_20260513T172244Z"),
    @("2026-05-14", "github_prizepicks_csv_20260514T162446Z"),
    @("2026-05-15", "github_prizepicks_csv_20260515T171127Z"),
    @("2026-05-16", "prizepicks_20260516T065109Z", "pp_json_fidelity_v1"),
    @("2026-05-17", "prizepicks_20260517T133520Z", "pp_json_fidelity_v1"),
    @("2026-05-18", "prizepicks_20260518T164128Z", "pp_json_fidelity_v1"),
    @("2026-05-19", "prizepicks_20260519T150832Z", "pp_json_fidelity_v1"),
    @("2026-05-20", "prizepicks_20260520T180552Z", "pp_json_fidelity_v1")
)

if ($ReplayDates.Count -gt 0) {
    $requested = @{}
    foreach ($date in $ReplayDates) {
        if ($date) {
            $requested[$date] = $true
        }
    }
    $items = @($items | Where-Object { $requested.ContainsKey($_[0]) })
    if ($items.Count -eq 0) {
        Write-Error "No replay items matched -ReplayDates: $($ReplayDates -join ', ')"
        exit 2
    }
}

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
$progressPath = Join-Path $OutputDir "progress.jsonl"
$summaryPath = Join-Path $OutputDir "sweep_summary.json"
$slipSummaryPath = Join-Path $OutputDir "slip_sweep_summary.json"
Remove-Item -Force -ErrorAction SilentlyContinue $progressPath

if (-not $SkipPreflight) {
    $preflightDates = $items | ForEach-Object { $_[0] }
    [pscustomobject]@{
        ts = (Get-Date).ToString("o")
        stage = "strict_preflight_start"
        dates = $preflightDates
    } | ConvertTo-Json -Compress | Add-Content -Encoding utf8 $progressPath

    $preflightArgs = @("run", "python", "scripts\mlb\preflight_strict_replay_dates.py", "--dates") + $preflightDates
    $preflightOutput = & uv @preflightArgs 2>&1
    $preflightExit = $LASTEXITCODE
    $preflightOutput | Set-Content -Encoding utf8 (Join-Path $OutputDir "strict_preflight_stdout.txt")
    if ($preflightExit -ne 0) {
        [pscustomobject]@{
            ts = (Get-Date).ToString("o")
            stage = "strict_preflight_failed"
            exit_code = $preflightExit
            stdout_path = (Join-Path $OutputDir "strict_preflight_stdout.txt")
        } | ConvertTo-Json -Compress | Add-Content -Encoding utf8 $progressPath
        Write-Error "Strict replay preflight failed. See $(Join-Path $OutputDir 'strict_preflight_stdout.txt')"
        exit $preflightExit
    }
    [pscustomobject]@{
        ts = (Get-Date).ToString("o")
        stage = "strict_preflight_complete"
        stdout_path = (Join-Path $OutputDir "strict_preflight_stdout.txt")
    } | ConvertTo-Json -Compress | Add-Content -Encoding utf8 $progressPath
}

foreach ($item in $items) {
    $date = $item[0]
    $board = $item[1]
    $itemRunIdSuffix = if ($RunIdSuffix -ne "github_csv_fidelity_v1") {
        $RunIdSuffix
    } elseif ($item.Count -ge 3 -and $item[2]) {
        $item[2]
    } else {
        $RunIdSuffix
    }
    $dateKey = $date.Replace("-", "")
    $runId = "replay_single_${dateKey}_${itemRunIdSuffix}"
    $runLog = Join-Path $OutputDir "$runId.run.json"
    $evalLog = Join-Path $OutputDir "$runId.eval.json"
    $errorLog = Join-Path $OutputDir "$runId.error.txt"
    $normalizedDir = "data\mlb\staged\board\$board"

    [pscustomobject]@{
        ts = (Get-Date).ToString("o")
        date = $date
        run_id = $runId
        stage = "run_board_start"
    } | ConvertTo-Json -Compress | Add-Content -Encoding utf8 $progressPath

    $runArgs = @(
        "run", "atlas-mlb", "run", "board",
        "--normalized-dir", $normalizedDir,
        "--run-id", $runId,
        "--date", $date,
        "--run-mode", "replay_single",
        "--json"
    )
    if (-not $RefreshBettingProsOdds) {
        $runArgs += "--no-bettingpros-odds-refresh"
    }
    if ($CalibrationArtifact) {
        $runArgs += @("--calibration-artifact", $CalibrationArtifact)
    }
    & uv @runArgs > $runLog 2> $errorLog
    $runExit = $LASTEXITCODE
    if ($runExit -ne 0) {
        [pscustomobject]@{
            ts = (Get-Date).ToString("o")
            date = $date
            run_id = $runId
            stage = "run_board_failed"
            exit_code = $runExit
            error_log = $errorLog
        } | ConvertTo-Json -Compress | Add-Content -Encoding utf8 $progressPath
        continue
    }

    [pscustomobject]@{
        ts = (Get-Date).ToString("o")
        date = $date
        run_id = $runId
        stage = "eval_start"
    } | ConvertTo-Json -Compress | Add-Content -Encoding utf8 $progressPath

    & uv run atlas-mlb audit eval --run-id $runId --json > $evalLog 2>> $errorLog
    $evalExit = $LASTEXITCODE
    if ($evalExit -ne 0) {
        [pscustomobject]@{
            ts = (Get-Date).ToString("o")
            date = $date
            run_id = $runId
            stage = "eval_failed"
            exit_code = $evalExit
            error_log = $errorLog
        } | ConvertTo-Json -Compress | Add-Content -Encoding utf8 $progressPath
        continue
    }

    [pscustomobject]@{
        ts = (Get-Date).ToString("o")
        date = $date
        run_id = $runId
        stage = "eval_complete"
        run_log = $runLog
        eval_log = $evalLog
    } | ConvertTo-Json -Compress | Add-Content -Encoding utf8 $progressPath
}

$aggregateOutput = & uv run python scripts\mlb\aggregate_fidelity_replay_sweep.py --input-dir $OutputDir 2>&1
$aggregateExit = $LASTEXITCODE
$aggregateOutput | Set-Content -Encoding utf8 $summaryPath
if ($aggregateExit -ne 0) {
    [pscustomobject]@{
        ts = (Get-Date).ToString("o")
        stage = "aggregate_failed"
        exit_code = $aggregateExit
        summary_path = $summaryPath
    } | ConvertTo-Json -Compress | Add-Content -Encoding utf8 $progressPath
    exit $aggregateExit
}

$slipAggregateOutput = & uv run python scripts\mlb\aggregate_slip_replay_eval.py --input-dir $OutputDir 2>&1
$slipAggregateExit = $LASTEXITCODE
$slipAggregateOutput | Set-Content -Encoding utf8 $slipSummaryPath
if ($slipAggregateExit -ne 0) {
    [pscustomobject]@{
        ts = (Get-Date).ToString("o")
        stage = "slip_aggregate_failed"
        exit_code = $slipAggregateExit
        summary_path = $slipSummaryPath
    } | ConvertTo-Json -Compress | Add-Content -Encoding utf8 $progressPath
    exit $slipAggregateExit
}
