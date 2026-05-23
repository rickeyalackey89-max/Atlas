param(
    [string]$Date = "",
    [string]$RunId = "",
    [ValidateSet("auto", "live", "replay", "test")]
    [string]$RunScope = "auto",
    [switch]$SkipBoxscoreFetch,
    [string]$LogRoot = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $repoRoot
$atlasRoot = Split-Path -Parent $repoRoot
$atlasPython = Join-Path $atlasRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $atlasPython)) {
    throw "Shared Atlas Python not found: $atlasPython. Run from Atlas root: uv sync --python 3.11"
}
$atlasPythonPath = @(
    (Join-Path $atlasRoot "NBA\src"),
    (Join-Path $atlasRoot "MLB\src")
) | Where-Object { Test-Path -LiteralPath $_ }
$oldPythonPath = $env:PYTHONPATH
if ($oldPythonPath) {
    $env:PYTHONPATH = "$($atlasPythonPath -join ';');$oldPythonPath"
} else {
    $env:PYTHONPATH = ($atlasPythonPath -join ";")
}

if ([string]::IsNullOrWhiteSpace($Date)) {
    $Date = (Get-Date).Date.AddDays(-1).ToString("yyyy-MM-dd")
}
$dateKey = $Date.Replace("-", "")

if ([string]::IsNullOrWhiteSpace($LogRoot)) {
    $LogRoot = Join-Path $repoRoot "data\mlb\eval\morning_prior_day_$dateKey"
}
New-Item -ItemType Directory -Force -Path $LogRoot | Out-Null

function Write-ProgressJson {
    param([hashtable]$Item)
    $Item["ts"] = (Get-Date).ToString("o")
    $Item | ConvertTo-Json -Compress | Add-Content -Encoding utf8 (Join-Path $LogRoot "progress.jsonl")
}

function Invoke-LoggedCommand {
    param(
        [string]$Stage,
        [string]$StageRunId = "",
        [string[]]$CommandArgs,
        [string]$OutputPath
    )

    Write-ProgressJson @{ stage = "${Stage}_start"; date = $Date; run_id = $StageRunId }
    $oldErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $output = & $CommandArgs[0] @($CommandArgs[1..($CommandArgs.Count - 1)]) 2>&1
    $ErrorActionPreference = $oldErrorActionPreference
    $exitCode = $LASTEXITCODE
    $output | Set-Content -Encoding utf8 $OutputPath
    if ($exitCode -ne 0) {
        Write-ProgressJson @{ stage = "${Stage}_failed"; date = $Date; run_id = $StageRunId; exit_code = $exitCode; log = $OutputPath }
        throw "${Stage} failed with exit code $exitCode. See $OutputPath"
    }
    Write-ProgressJson @{ stage = "${Stage}_complete"; date = $Date; run_id = $StageRunId; log = $OutputPath }
}

function Resolve-RunIdsForDate {
    param([string]$TargetDate, [string]$Scope)

    $targetDateKey = $TargetDate.Replace("-", "")
    $roots = @()
    if ($Scope -eq "live") {
        $roots = @(Join-Path $repoRoot "data\mlb\live_runs")
    } elseif ($Scope -eq "replay") {
        $roots = @(Join-Path $repoRoot "data\mlb\replay_runs")
    } elseif ($Scope -eq "test") {
        $roots = @(Join-Path $repoRoot "data\mlb\test_runs")
    } else {
        $roots = @(
            (Join-Path $repoRoot "data\mlb\live_runs"),
            (Join-Path $repoRoot "data\mlb\replay_runs"),
            (Join-Path $repoRoot "data\mlb\test_runs"),
            (Join-Path $repoRoot "data\mlb\runs")
        )
    }

    $candidates = @()
    for ($i = 0; $i -lt $roots.Count; $i++) {
        $root = $roots[$i]
        if (-not (Test-Path -LiteralPath $root)) {
            continue
        }
        Get-ChildItem -LiteralPath $root -Directory | ForEach-Object {
            $manifestPath = Join-Path $_.FullName "run_manifest.json"
            $scoredPath = Join-Path $_.FullName "scored_legs.json"
            $dateMatched = $false
            if (Test-Path -LiteralPath $manifestPath) {
                $manifestRaw = Get-Content -Raw -LiteralPath $manifestPath
                $manifestDate = ""
                $dateMatches = [regex]::Matches($manifestRaw, '"game_date_filter"\s*:\s*"([^"]+)"')
                if ($dateMatches.Count -gt 0) {
                    $manifestDate = [string]$dateMatches[0].Groups[1].Value
                }
                $dateMatched = $manifestDate -eq $TargetDate
            } elseif ($_.Name -like "*$targetDateKey*") {
                $dateMatched = Test-Path -LiteralPath $scoredPath
            }

            if ($dateMatched -and (Test-Path -LiteralPath $scoredPath)) {
                $candidates += [pscustomobject]@{
                    RunId = $_.Name
                    Priority = $i
                    LastWriteTimeUtc = $_.LastWriteTimeUtc
                    Path = $_.FullName
                }
            }
        }
    }

    # Live run folders are the source of truth for fresh evaluation, but the
    # runtime summary catches edge cases where a late-night run has already
    # been evaluated and its live folder is unavailable. Do not let that run
    # disappear from the 6AM report silently.
    $summaryPath = Join-Path $repoRoot "data\mlb\runtime_state\runs\run_summaries.jsonl"
    if (($Scope -eq "live" -or $Scope -eq "auto") -and (Test-Path -LiteralPath $summaryPath)) {
        foreach ($line in Get-Content -LiteralPath $summaryPath) {
            if ([string]::IsNullOrWhiteSpace($line)) {
                continue
            }
            try {
                $summary = $line | ConvertFrom-Json
            } catch {
                continue
            }
            if ([string]$summary.game_date -ne $TargetDate) {
                continue
            }
            if ([string]$summary.run_mode -ne "live") {
                continue
            }
            $summaryRunId = [string]$summary.run_id
            if ([string]::IsNullOrWhiteSpace($summaryRunId)) {
                continue
            }
            $candidatePath = Join-Path (Join-Path $repoRoot "data\mlb\live_runs") $summaryRunId
            $publishedUtc = [datetime]::MinValue
            if (-not [string]::IsNullOrWhiteSpace([string]$summary.published_at_utc)) {
                [datetime]::TryParse([string]$summary.published_at_utc, [ref]$publishedUtc) | Out-Null
            }
            $candidates += [pscustomobject]@{
                RunId = $summaryRunId
                Priority = 0
                LastWriteTimeUtc = $publishedUtc
                Path = $candidatePath
            }
        }
    }

    if ($candidates.Count -eq 0) {
        throw "No scored MLB run found for $TargetDate in scope '$Scope'. Pass -RunId explicitly if needed."
    }

    if ($Scope -eq "auto") {
        $bestPriority = ($candidates | Measure-Object -Property Priority -Minimum).Minimum
        $candidates = @($candidates | Where-Object { $_.Priority -eq $bestPriority })
    }
    return @($candidates | Sort-Object Priority, LastWriteTimeUtc, RunId | Select-Object -ExpandProperty RunId -Unique)
}

function Resolve-ScoredRunPath {
    param([string]$TargetRunId)
    $roots = @(
        (Join-Path $repoRoot "data\mlb\live_runs"),
        (Join-Path $repoRoot "data\mlb\replay_runs"),
        (Join-Path $repoRoot "data\mlb\test_runs"),
        (Join-Path $repoRoot "data\mlb\runs")
    )
    foreach ($root in $roots) {
        $path = Join-Path (Join-Path $root $TargetRunId) "scored_legs.json"
        if (Test-Path -LiteralPath $path) {
            return $path
        }
    }
    return ""
}

function Test-ExistingEvalComplete {
    param([string]$TargetRunId)
    $evalDir = Join-Path $repoRoot "data\mlb\eval\$TargetRunId"
    return (
        (Test-Path -LiteralPath (Join-Path $evalDir "eval_manifest.json")) -and
        (Test-Path -LiteralPath (Join-Path $evalDir "eval_legs.csv")) -and
        (Test-Path -LiteralPath (Join-Path $evalDir "eval_slips.csv"))
    )
}

function Publish-ExistingEvalLatest {
    param([string]$TargetRunId)
    $evalRoot = Join-Path $repoRoot "data\mlb\eval"
    $evalDir = Join-Path $evalRoot $TargetRunId
    $copies = @(
        @("eval_legs.csv", "latest_eval_legs.csv"),
        @("eval_legs.json", "latest_eval_legs.json"),
        @("eval_summary.json", "latest_eval_summary.json"),
        @("eval_manifest.json", "latest_eval_manifest.json"),
        @("slip_eval.json", "latest_slip_eval.json"),
        @("eval_slips.csv", "latest_eval_slips.csv"),
        @("eval_slips.json", "latest_eval_slips.json")
    )
    foreach ($copy in $copies) {
        $source = Join-Path $evalDir $copy[0]
        $destination = Join-Path $evalRoot $copy[1]
        if (Test-Path -LiteralPath $source) {
            Copy-Item -LiteralPath $source -Destination $destination -Force
        }
    }
}

if (-not $SkipBoxscoreFetch) {
    Invoke-LoggedCommand `
        -Stage "fetch_boxscores" `
        -StageRunId "" `
        -CommandArgs @($atlasPython, "-m", "mlb.cli", "fetch", "statsapi-boxscores-bulk", "--start-date", $Date, "--end-date", $Date, "--json") `
        -OutputPath (Join-Path $LogRoot "fetch_boxscores.json")
}

$runIds = @()
if ([string]::IsNullOrWhiteSpace($RunId)) {
    $runIds = @(Resolve-RunIdsForDate -TargetDate $Date -Scope $RunScope)
} else {
    $runIds = @($RunId)
}

$runResults = @()
foreach ($targetRunId in $runIds) {
    $safeRunId = $targetRunId -replace '[^A-Za-z0-9_.-]', '_'
    $evalDir = Join-Path $repoRoot "data\mlb\eval\$targetRunId"
    $scoredRunPath = Resolve-ScoredRunPath -TargetRunId $targetRunId
    if ([string]::IsNullOrWhiteSpace($scoredRunPath)) {
        if (Test-ExistingEvalComplete -TargetRunId $targetRunId) {
            Publish-ExistingEvalLatest -TargetRunId $targetRunId
            $reuseLog = Join-Path $LogRoot "audit_eval_$safeRunId.json"
            [pscustomobject]@{
                date = $Date
                run_id = $targetRunId
                status = "existing_eval_reused"
                reason = "missing_scored_run_folder_existing_eval_reused"
                eval_dir = $evalDir
            } | ConvertTo-Json -Depth 4 | Set-Content -Encoding utf8 -LiteralPath $reuseLog
            Write-ProgressJson @{
                stage = "audit_eval_existing_reused"
                date = $Date
                run_id = $targetRunId
                reason = "missing_scored_run_folder_existing_eval_reused"
                eval_dir = $evalDir
                log = $reuseLog
            }
        } else {
            throw "Run $targetRunId is listed for $Date but has no scored_legs.json and no complete eval folder."
        }
    } else {
        Invoke-LoggedCommand `
            -Stage "audit_eval" `
            -StageRunId $targetRunId `
            -CommandArgs @($atlasPython, "-m", "mlb.cli", "audit", "eval", "--run-id", $targetRunId, "--json") `
            -OutputPath (Join-Path $LogRoot "audit_eval_$safeRunId.json")
    }

    $runResults += [pscustomobject]@{
        date = $Date
        run_id = $targetRunId
        eval_dir = $evalDir
        eval_legs_csv = Join-Path $evalDir "eval_legs.csv"
        eval_legs_json = Join-Path $evalDir "eval_legs.json"
        eval_slips_csv = Join-Path $evalDir "eval_slips.csv"
        eval_slips_json = Join-Path $evalDir "eval_slips.json"
        slip_eval_json = Join-Path $evalDir "slip_eval.json"
        log = Join-Path $LogRoot "audit_eval_$safeRunId.json"
    }
}

$result = [pscustomobject]@{
    date = $Date
    run_scope = $RunScope
    run_count = $runResults.Count
    run_ids = @($runResults | Select-Object -ExpandProperty run_id)
    runs = $runResults
    logs = $LogRoot
}
$result | ConvertTo-Json -Depth 5 | Set-Content -Encoding utf8 (Join-Path $LogRoot "result.json")
$result | ConvertTo-Json -Depth 5
